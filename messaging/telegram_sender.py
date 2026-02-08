import logging
import asyncio
from telegram import Bot
import config

logger = logging.getLogger("TELEGRAM")


async def _send_to_chat(bot: Bot, chat_id: str, message: str, image_url: str, link: str):
    caption = f"{message}\n\n🔗 {link}" if link else message
    if image_url:
        await bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption)
    else:
        await bot.send_message(chat_id=chat_id, text=caption)
    logger.info(f"Enviado para grupo {chat_id} com sucesso")


async def _send_all(message: str, image_url: str, affiliate_link: str):
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não configurado, pulando envio")
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")
    if not config.TELEGRAM_CHAT_IDS:
        logger.warning("TELEGRAM_CHAT_IDS vazio, pulando envio")
        raise RuntimeError("TELEGRAM_CHAT_IDS vazio")

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    logger.info(f"Enviando para {len(config.TELEGRAM_CHAT_IDS)} grupos...")

    errors = []
    for chat_id in config.TELEGRAM_CHAT_IDS:
        try:
            await _send_to_chat(bot, chat_id, message, image_url, affiliate_link)
        except Exception as e:
            logger.error(f"ERRO ao enviar para grupo {chat_id}: {e}")
            errors.append(str(e))

    if len(errors) == len(config.TELEGRAM_CHAT_IDS):
        raise RuntimeError(f"Falha em todos os grupos Telegram: {'; '.join(errors)}")


def send_message(message: str, image_url: str = "", affiliate_link: str = ""):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _send_all(message, image_url, affiliate_link)).result()
        else:
            loop.run_until_complete(_send_all(message, image_url, affiliate_link))
    except RuntimeError as e:
        if "no current event loop" in str(e).lower() or "no running event loop" in str(e).lower():
            asyncio.run(_send_all(message, image_url, affiliate_link))
        else:
            raise
