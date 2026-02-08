import json
import logging
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import config

logger = logging.getLogger("BROWSER")


def _build_options(headless: bool = False) -> Options:
    options = Options()
    if config.CHROME_BINARY:
        options.binary_location = config.CHROME_BINARY
    if headless:
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
    options = _build_options(headless=config.HEADLESS)
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
