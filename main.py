import logging
import signal
import sys
from apscheduler.schedulers.blocking import BlockingScheduler

import config
from database import db
from scraper.browser import get_driver, stop_virtual_display, load_store_cookies, save_store_cookies
from scraper.pelando_scraper import scrape_pelando
from scraper.stores import STORE_HANDLERS
from ai.message_generator import generate_message, extract_title
from messaging import telegram_sender, whatsapp_sender

logger = logging.getLogger("MAIN")

driver = None
scheduler = None
_shutting_down = False
_logged_in_stores: set[str] = set()  # Lojas com sessão ativa


def ensure_store_logins(drv):
    """Verifica login em todas as lojas. Carrega cookies e faz login manual se necessário."""
    global _logged_in_stores
    _logged_in_stores.clear()

    for store_name, handler in STORE_HANDLERS.items():
        logger.info(f"Verificando login para {handler.display_name}...")

        # 1. Carregar cookies salvos
        load_store_cookies(drv, handler.name, handler.domain_url)

        # 2. Verificar se está logado
        if handler.is_logged_in(drv):
            logger.info(f"{handler.display_name}: sessão ativa")
            _logged_in_stores.add(handler.name)
            continue

        # 3. Se headless, não pode fazer login interativo
        if config.HEADLESS:
            logger.warning(
                f"{handler.display_name}: sem sessão válida (headless, não é possível login interativo). "
                f"Deals desta loja serão ignorados até ter cookies válidos."
            )
            continue

        # 4. Login manual (modo local)
        logger.info(f"{handler.display_name}: sessão expirada, iniciando login manual...")
        if handler.login(drv):
            save_store_cookies(drv, handler.name)
            _logged_in_stores.add(handler.name)
            logger.info(f"{handler.display_name}: login realizado e cookies salvos")
        else:
            logger.error(f"{handler.display_name}: falha no login")


def _ensure_driver():
    """Recria o driver se ele morreu."""
    global driver
    try:
        driver.current_url
    except Exception:
        logger.warning("WebDriver inativo, recriando...")
        try:
            driver.quit()
        except Exception:
            pass
        driver = get_driver()
        ensure_store_logins(driver)
        logger.info("WebDriver recriado com sucesso")


def scrape_and_send():
    global driver
    logger.info("=" * 60)
    logger.info("Início do ciclo de scraping")
    logger.info("=" * 60)

    try:
        _ensure_driver()
        products = scrape_pelando(driver, _logged_in_stores)

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
                    # Salvar frase de abertura usada
                    title = extract_title(message)
                    if title:
                        db.save_used_title(title)
                    # Adicionar linha de cupom com formatação monospace (backticks)
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
                if product.store == "amazon" and "amzn.to" not in product.affiliate_link:
                    logger.warning(f"Link Amazon inválido para {product.mlb_id}: {product.affiliate_link[:80]} - pulando produto")
                    errors += 1
                    continue
                if product.store == "mercado_livre" and "/sec/" not in product.affiliate_link:
                    logger.warning(f"Link ML inválido para {product.mlb_id}: {product.affiliate_link[:80]} - pulando produto")
                    errors += 1
                    continue

                # Determinar canais por loja (busca TELEGRAM_CHAT_IDS_{STORE}, fallback para default)
                tg_ids = config.get_telegram_ids(product.store) if product.store else config.TELEGRAM_CHAT_IDS
                wa_ids = config.get_whatsapp_ids(product.store) if product.store else config.WHATSAPP_GROUP_IDS

                # Enviar para canais - rastrear sucesso
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

                # Só salva no banco se pelo menos um canal teve sucesso
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


def shutdown(signum, frame):
    global driver, scheduler, _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    logger.info("Recebido sinal de encerramento, finalizando...")

    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

    if driver:
        try:
            driver.quit()
            logger.info("WebDriver encerrado")
        except Exception:
            pass

    stop_virtual_display()

    sys.exit(0)


def main():
    global driver, scheduler

    config.setup_logging()
    logger.info("KOP-ML iniciando...")

    # Inicializar banco
    db.init_db()

    # Inicializar browser e verificar logins
    driver = get_driver()
    ensure_store_logins(driver)

    # Registrar signal handlers para graceful shutdown
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Limpar dados antigos ao iniciar
    db.cleanup_old_products(days=7)
    db.cleanup_old_deals(days=1)

    # Executar primeira vez imediatamente
    scrape_and_send()

    # Agendar execuções periódicas
    scheduler = BlockingScheduler()
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

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        shutdown(None, None)


if __name__ == "__main__":
    main()
