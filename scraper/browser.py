import json
import logging
import os
import platform
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import config

logger = logging.getLogger("BROWSER")

_display = None


def _start_virtual_display():
    """Inicia Xvfb virtual display no Linux (substitui --headless para evitar detecção)."""
    global _display
    if platform.system() != "Linux":
        return False
    try:
        from pyvirtualdisplay import Display
        _display = Display(visible=0, size=(1920, 1080))
        _display.start()
        logger.info("Virtual display (Xvfb) iniciado - Chrome rodará em modo GUI")
        return True
    except ImportError:
        logger.warning("PyVirtualDisplay não instalado, usando --headless=new")
    except Exception as e:
        logger.warning(f"Falha ao iniciar Xvfb: {e}, usando --headless=new")
    return False


def stop_virtual_display():
    """Para o Xvfb virtual display se estiver rodando."""
    global _display
    if _display:
        try:
            _display.stop()
            logger.info("Virtual display (Xvfb) parado")
        except Exception:
            pass
        _display = None


def _build_options(headless: bool = False, use_xvfb: bool = False) -> Options:
    options = Options()
    if config.CHROME_BINARY:
        options.binary_location = config.CHROME_BINARY
    # Só usa --headless se Xvfb não estiver disponível
    if headless and not use_xvfb:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return options


def _cookies_path(store_name: str) -> str:
    """Retorna o caminho do arquivo de cookies para uma loja."""
    return os.path.join(config._data_dir, f"cookies_{store_name}.json")


def save_store_cookies(driver: webdriver.Chrome, store_name: str):
    """Salva cookies do browser para uma loja específica."""
    path = _cookies_path(store_name)
    cookies = driver.get_cookies()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f)
    logger.info(f"Cookies salvos para {store_name} ({len(cookies)} cookies)")


def load_store_cookies(driver: webdriver.Chrome, store_name: str, domain_url: str) -> bool:
    """Carrega cookies de uma loja. Navega para o domínio antes de adicionar."""
    path = _cookies_path(store_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        driver.get(domain_url)
        time.sleep(1)
        for cookie in cookies:
            cookie.pop("sameSite", None)
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        logger.info(f"Cookies carregados para {store_name} ({len(cookies)} cookies)")
        return True
    except FileNotFoundError:
        logger.info(f"Sem cookies salvos para {store_name}")
        return False


def get_driver() -> webdriver.Chrome:
    """Cria e retorna o WebDriver. Não faz login em nenhuma loja."""
    logger.info(f"Iniciando Chrome WebDriver (headless={config.HEADLESS})...")

    use_xvfb = False
    if config.HEADLESS:
        use_xvfb = _start_virtual_display()

    options = _build_options(headless=config.HEADLESS, use_xvfb=use_xvfb)
    service = Service(executable_path=config.CHROMEDRIVER_PATH) if config.CHROMEDRIVER_PATH else Service()
    driver = webdriver.Chrome(options=options, service=service)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )

    logger.info("WebDriver criado com sucesso")
    return driver
