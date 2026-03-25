import logging
import os
import nodriver as uc
from pyvirtualdisplay import Display
import config

logger = logging.getLogger("BROWSER")

_display: Display | None = None

# Diretório persistente do perfil Chrome (mantém sessões logadas entre restarts)
CHROME_PROFILE_DIR = os.path.join(config._data_dir, "chrome_profile")


def start_virtual_display():
    """Inicia Xvfb quando HEADLESS=true (nodriver precisa de display real)."""
    global _display
    if config.HEADLESS and _display is None:
        _display = Display(visible=False, size=(1920, 1080))
        _display.start()
        logger.info("PyVirtualDisplay (Xvfb) iniciado")


def stop_virtual_display():
    """Para o Xvfb se estiver rodando."""
    global _display
    if _display:
        _display.stop()
        _display = None
        logger.info("PyVirtualDisplay parado")


async def get_browser() -> uc.Browser:
    """Cria e retorna o browser nodriver com perfil persistente."""
    start_virtual_display()
    logger.info("Iniciando nodriver browser...")

    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)

    browser_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
    ]

    browser = await uc.start(
        headless=False,
        user_data_dir=CHROME_PROFILE_DIR,
        browser_args=browser_args,
        browser_executable_path=config.CHROME_BINARY or None,
    )

    logger.info("nodriver browser criado com sucesso")
    return browser
