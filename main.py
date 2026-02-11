import logging
import signal
import sys
from apscheduler.schedulers.blocking import BlockingScheduler

import config
from database import db
from scraper.browser import get_driver, stop_virtual_display
from scraper.pelando_scraper import scrape_pelando
from ai.message_generator import generate_message, extract_title
from messaging import telegram_sender, whatsapp_sender

logger = logging.getLogger("MAIN")

driver = None
scheduler = None
_shutting_down = False


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
        logger.info("WebDriver recriado com sucesso")


def scrape_and_send():
    global driver
    logger.info("=" * 60)
    logger.info("Início do ciclo de scraping")
    logger.info("=" * 60)

    try:
        _ensure_driver()
        products = scrape_pelando(driver)

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

                # Validar link de afiliado (deve conter /sec/)
                if not product.affiliate_link or "/sec/" not in product.affiliate_link:
                    logger.warning(f"Link de afiliado inválido para {product.mlb_id} ({product.title[:50]}): {product.affiliate_link[:80] if product.affiliate_link else 'vazio'} - pulando produto")
                    errors += 1
                    continue

                # Enviar para canais - rastrear sucesso
                telegram_ok = False
                whatsapp_ok = False

                try:
                    telegram_sender.send_message(
                        message=message,
                        image_url=product.image_url,
                        affiliate_link=product.affiliate_link,
                    )
                    telegram_ok = True
                except Exception as e:
                    logger.error(f"ERRO Telegram para {product.mlb_id} ({product.title[:50]}): {e}")

                try:
                    whatsapp_sender.send_message(
                        message=message,
                        image_url=product.image_url,
                        affiliate_link=product.affiliate_link,
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

    # Inicializar browser
    driver = get_driver()

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
