import json
import logging
import os
import time
import undetected_chromedriver as uc
import config

logger = logging.getLogger("BROWSER")


def _cookies_path(store_name: str) -> str:
    """Retorna o caminho do arquivo de cookies para uma loja."""
    return os.path.join(config._data_dir, f"cookies_{store_name}.json")


def save_store_cookies(driver, store_name: str):
    """Salva cookies do browser para uma loja específica."""
    path = _cookies_path(store_name)
    cookies = driver.get_cookies()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f)
    logger.info(f"Cookies salvos para {store_name} ({len(cookies)} cookies)")


def load_store_cookies(driver, store_name: str, domain_url: str) -> bool:
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


def get_driver() -> uc.Chrome:
    """Cria e retorna o WebDriver com undetected-chromedriver."""
    logger.info(f"Iniciando Chrome WebDriver (headless={config.HEADLESS})...")

    options = uc.ChromeOptions()
    if config.CHROME_BINARY:
        options.binary_location = config.CHROME_BINARY
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = uc.Chrome(
        options=options,
        headless=config.HEADLESS,
        use_subprocess=True,
        driver_executable_path=config.CHROMEDRIVER_PATH or None,
    )

    logger.info("WebDriver criado com sucesso")
    return driver


def stop_virtual_display():
    """Mantido para compatibilidade - não faz nada com undetected-chromedriver."""
    pass
