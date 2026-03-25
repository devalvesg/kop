import asyncio
import logging
import signal
import sys
import nodriver as uc
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database import db
from scraper.browser import get_browser, stop_virtual_display
from scraper.pelando_scraper import scrape_pelando
from scraper.stores import STORE_HANDLERS
from ai.message_generator import generate_message, extract_title
from messaging import telegram_sender, whatsapp_sender

logger = logging.getLogger("MAIN")

browser = None
scheduler = None
_shutting_down = False
_logged_in_stores: set[str] = set()


async def ensure_store_logins():
    """Verifica login em todas as lojas usando o perfil persistente do Chrome."""
    global _logged_in_stores
    _logged_in_stores.clear()

    for store_name, handler in STORE_HANDLERS.items():
        logger.info(f"Verificando login para {handler.display_name}...")

        if await handler.is_logged_in(browser):
            logger.info(f"{handler.display_name}: sessão ativa")
            _logged_in_stores.add(handler.name)
            continue

        if config.HEADLESS:
            logger.warning(
                f"{handler.display_name}: sem sessão válida (headless, não é possível login interativo). "
                f"Deals desta loja serão ignorados até ter cookies válidos."
            )
            continue

        logger.info(f"{handler.display_name}: sessão expirada, iniciando login manual...")
        if await handler.login(browser):
            _logged_in_stores.add(handler.name)
            logger.info(f"{handler.display_name}: login realizado")
        else:
            logger.error(f"{handler.display_name}: falha no login")


async def _ensure_browser():
    """Recria o browser se ele morreu."""
    global browser
    try:
        _ = browser.tabs
    except Exception:
        logger.warning("Browser inativo, recriando...")
        try:
            browser.stop()
        except Exception:
            pass
        browser = await get_browser()
        await ensure_store_logins()
        logger.info("Browser recriado com sucesso")


async def scrape_and_send():
    global browser
    logger.info("=" * 60)
    logger.info("Início do ciclo de scraping")
    logger.info("=" * 60)

    try:
        await _ensure_browser()
        tab = browser.main_tab
        products = await scrape_pelando(tab, _logged_in_stores)

        if not products:
            logger.info("Nenhum produto novo encontrado neste ciclo")
            return

        processed = 0
        errors = 0

        for product in products:
            try:
                # Gerar mensagem com IA - se falhar, pula o produto
                try:
                    used_titles = db.get_used_titles()
                    message = generate_message(product, used_titles=used_titles)
                    title = extract_title(message)
                    if title:
                        db.save_used_title(title)
                    if product.coupon:
                        message = f"{message}\n\n`Cupom de {product.coupon}`"
                except Exception as e:
                    errors += 1
                    logger.error(f"ERRO ao gerar mensagem para {product.mlb_id} ({product.title[:50]}): {e} - produto será reprocessado no próximo ciclo")
                    continue

                # Validar link de afiliado por loja
                if not product.affiliate_link:
                    logger.warning(f"Link de afiliado vazio para {product.mlb_id} ({product.title[:50]}) - pulando produto")
                    errors += 1
                    continue
                if product.store == "amazon" and "amzn.to" not in product.affiliate_link and "amazon.com.br" not in product.affiliate_link:
                    logger.warning(f"Link Amazon inválido para {product.mlb_id}: {product.affiliate_link[:80]} - pulando produto")
                    errors += 1
                    continue
                if product.store == "mercado_livre" and "/sec/" not in product.affiliate_link and "meli.la" not in product.affiliate_link:
                    logger.warning(f"Link ML inválido para {product.mlb_id}: {product.affiliate_link[:80]} - pulando produto")
                    errors += 1
                    continue

                # Determinar canais por loja
                tg_ids = config.get_telegram_ids(product.store) if product.store else config.TELEGRAM_CHAT_IDS
                wa_ids = config.get_whatsapp_ids(product.store) if product.store else config.WHATSAPP_GROUP_IDS

                # Enviar para canais
                telegram_ok = False
                whatsapp_ok = False

                try:
                    telegram_sender.send_message(
                        message=message,
                        image_url=product.image_url,
                        affiliate_link=product.affiliate_link,
                        chat_ids=tg_ids,
                    )
                    telegram_ok = True
                except Exception as e:
                    logger.error(f"ERRO Telegram para {product.mlb_id} ({product.title[:50]}): {e}")

                try:
                    whatsapp_sender.send_message(
                        message=message,
                        image_url=product.image_url,
                        affiliate_link=product.affiliate_link,
                        group_ids=wa_ids,
                    )
                    whatsapp_ok = True
                except Exception as e:
                    logger.error(f"ERRO WhatsApp para {product.mlb_id} ({product.title[:50]}): {e}")

                if telegram_ok or whatsapp_ok:
                    db.save_product(product)
                    processed += 1
                    logger.info(f"Produto {product.mlb_id} ({product.title[:50]}) processado com sucesso (TG={telegram_ok} WA={whatsapp_ok})")
                else:
                    errors += 1
                    logger.warning(
                        f"Produto {product.mlb_id} ({product.title[:50]}) NÃO salvo - falha em todos os canais, será reprocessado no próximo ciclo"
                    )

            except Exception as e:
                errors += 1
                logger.error(f"ERRO inesperado ao processar produto {product.mlb_id}: {e}")

        logger.info(
            f"Ciclo concluído: {processed} produtos processados, {errors} erros"
        )

    except Exception as e:
        logger.error(f"ERRO no ciclo de scraping: {e}")


def shutdown_sync():
    """Shutdown síncrono para signal handlers."""
    global browser, scheduler, _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    logger.info("Recebido sinal de encerramento, finalizando...")

    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

    if browser:
        try:
            browser.stop()
            logger.info("Browser encerrado")
        except Exception:
            pass

    stop_virtual_display()


async def main():
    global browser, scheduler

    config.setup_logging()
    logger.info("KOP-ML iniciando...")

    # Inicializar banco
    db.init_db()

    # Inicializar browser e verificar logins
    browser = await get_browser()
    await ensure_store_logins()

    # Registrar signal handlers para graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_sync)

    # Limpar dados antigos ao iniciar
    db.cleanup_old_products(days=7)
    db.cleanup_old_deals(days=1)

    # Executar primeira vez imediatamente
    await scrape_and_send()

    # Agendar execuções periódicas
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scrape_and_send,
        "interval",
        seconds=config.SCRAPE_INTERVAL_SECONDS,
    )
    scheduler.add_job(
        db.cleanup_old_products,
        "cron",
        hour=3,
        kwargs={"days": 7},
    )
    scheduler.add_job(
        db.cleanup_old_deals,
        "cron",
        hour=3,
        kwargs={"days": 1},
    )
    scheduler.add_job(
        db.cleanup_used_titles,
        "cron",
        hour=0,
        minute=0,
    )

    logger.info(
        f"Scheduler iniciado - scraping a cada {config.SCRAPE_INTERVAL_SECONDS}s, limpeza diária às 03:00, reset títulos às 00:00"
    )

    scheduler.start()

    # Manter o event loop rodando até sinal de shutdown
    try:
        while not _shutting_down:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        shutdown_sync()


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
