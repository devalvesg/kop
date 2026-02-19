import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

_env = os.getenv("APP_ENV", "dev")
load_dotenv(f".env.{_env}")

# Mercado Livre
ML_EMAIL = os.getenv("ML_EMAIL", "")

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
    if cid.strip()
]

# WhatsApp
WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:3001")
WHATSAPP_GROUP_IDS = [
    gid.strip()
    for gid in os.getenv("WHATSAPP_GROUP_IDS", "").split(",")
    if gid.strip()
]

# Scraper
SCRAPE_INTERVAL_SECONDS = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "60"))
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
CHROME_BINARY = os.getenv("CHROME_BINARY", "")  # Ex: /usr/bin/chromium-browser
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", "")  # Ex: /usr/bin/chromedriver

# URLs
PELANDO_URL = "https://www.pelando.com.br/"

# Paths - em Docker usa /app/data, localmente usa diretório do projeto
_base_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_base_dir, "data") if HEADLESS else _base_dir
os.makedirs(_data_dir, exist_ok=True)

DB_PATH = os.path.join(_data_dir, "products.db")
LOGS_DIR = os.path.join(_base_dir, "logs")


def get_telegram_ids(store: str) -> list[str]:
    """Retorna chat IDs do Telegram por loja. Padrão: TELEGRAM_CHAT_IDS_{STORE_UPPER}. Fallback: TELEGRAM_CHAT_IDS."""
    store_ids = [cid.strip() for cid in os.getenv(f"TELEGRAM_CHAT_IDS_{store.upper()}", "").split(",") if cid.strip()]
    return store_ids or TELEGRAM_CHAT_IDS


def get_whatsapp_ids(store: str) -> list[str]:
    """Retorna group IDs do WhatsApp por loja. Padrão: WHATSAPP_GROUP_IDS_{STORE_UPPER}. Fallback: WHATSAPP_GROUP_IDS."""
    store_ids = [gid.strip() for gid in os.getenv(f"WHATSAPP_GROUP_IDS_{store.upper()}", "").split(",") if gid.strip()]
    return store_ids or WHATSAPP_GROUP_IDS


def setup_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)

    log_format = "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        os.path.join(LOGS_DIR, "kop-ml.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(file_handler)
