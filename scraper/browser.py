import json
import logging
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


def _save_cookies(driver: webdriver.Chrome):
    cookies = driver.get_cookies()
    with open(config.COOKIES_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f)
    logger.info(f"Cookies salvos em {config.COOKIES_PATH}")


def _load_cookies(driver: webdriver.Chrome) -> bool:
    try:
        with open(config.COOKIES_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        driver.get(config.ML_LOGIN_URL)
        for cookie in cookies:
            cookie.pop("sameSite", None)
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        logger.info("Cookies carregados de cookies.json")
        return True
    except FileNotFoundError:
        logger.info("Arquivo cookies.json não encontrado")
        return False


def _is_logged_in(driver: webdriver.Chrome) -> bool:
    driver.get(config.ML_HUB_URL)
    time.sleep(3)
    current_url = driver.current_url
    logged_in = "login" not in current_url and "afiliados" in current_url
    if logged_in:
        logger.info("Sessão válida, navegando para hub de afiliados")
    else:
        logger.warning(f"Sessão inválida, redirecionado para: {current_url}")
    return logged_in


def get_driver() -> webdriver.Chrome:
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

    if _load_cookies(driver) and _is_logged_in(driver):
        return driver

    logger.warning("Sessão expirada ou primeiro login. Faça login manualmente no navegador.")
    driver.get("https://www.mercadolivre.com.br/navigation/login")

    print("\n" + "=" * 60)
    print("FAÇA LOGIN NO MERCADO LIVRE NO NAVEGADOR QUE ABRIU")
    print("Após fazer login, pressione ENTER aqui no terminal...")
    print("=" * 60 + "\n")
    input()

    _save_cookies(driver)

    if _is_logged_in(driver):
        return driver

    logger.error("Falha no login. Verifique suas credenciais.")
    driver.quit()
    raise RuntimeError("Não foi possível autenticar no Mercado Livre")
