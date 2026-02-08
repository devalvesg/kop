import logging
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from models.pelando_deal import PelandoDeal
from scraper.stores import get_handler, get_supported_stores
import config

logger = logging.getLogger("PELANDO")

# Seletores CSS do Pelando
SEL_FILTER_RECENTS = "a#FEED_RECENTS"  # Filtro "Recentes" na página inicial
# O card principal tem data-show-author (true ou false)
SEL_DEAL_CARD = "div[data-show-author]"
SEL_CARD_TITLE = "h3[class*='title'] a"
SEL_CARD_PRICE = "span[class*='deal-card-stamp']"
SEL_CARD_IMAGE = "img[class*='deal-card-image']"
# LOJA - usar XPath pois CSS selector não funciona corretamente
SEL_CARD_STORE_XPATH = ".//a[contains(@href, '/cupons-de-descontos/')]"
SEL_CARD_TEMPERATURE = "div[class*='deal-card-temperature'] span"
SEL_CARD_ACTION = "a[class*='deal-card-action']"

# Quantidade máxima de deals a processar por ciclo
MAX_DEALS_TO_PROCESS = 10


def _is_expired(card) -> bool:
    """Verifica se o deal está expirado."""
    try:
        # Verificar data-inactive="true" no título (link principal)
        title_link = card.find_element(By.CSS_SELECTOR, SEL_CARD_TITLE)
        if title_link.get_attribute("data-inactive") == "true":
            return True

        # Verificar se existe label "Expirada"
        expired_labels = card.find_elements(By.CSS_SELECTOR, "[class*='inactive-label']")
        for label in expired_labels:
            if "expirada" in label.text.lower():
                return True

        return False
    except Exception:
        return False


def _is_coupon(title: str) -> bool:
    """Verifica se o deal é um cupom (não queremos cupons)."""
    return "cupom" in title.lower()


def _extract_deal_data(card) -> PelandoDeal | None:
    """Extrai dados de um card de deal do Pelando."""
    try:
        # Verificar se está expirado
        if _is_expired(card):
            logger.debug("Deal expirado, pulando")
            return None

        # Título e URL do deal
        try:
            title_el = card.find_element(By.CSS_SELECTOR, SEL_CARD_TITLE)
            title = title_el.text.strip()
            deal_url = title_el.get_attribute("href")
        except NoSuchElementException:
            logger.debug("Card sem título, pulando")
            return None

        # Verificar se é cupom
        if _is_coupon(title):
            logger.debug(f"Deal é cupom, pulando: {title[:40]}")
            return None

        # Preço
        price = ""
        try:
            price_el = card.find_element(By.CSS_SELECTOR, SEL_CARD_PRICE)
            price_text = price_el.text.strip()
            # Formato: "R$\n493" ou similar
            price = price_text.replace("\n", " ").strip()
            if not price.startswith("R$"):
                price = f"R$ {price}"
        except NoSuchElementException:
            pass

        # Imagem
        image_url = ""
        try:
            image_el = card.find_element(By.CSS_SELECTOR, SEL_CARD_IMAGE)
            image_url = image_el.get_attribute("src") or ""
        except NoSuchElementException:
            pass

        # Loja (vendido por) - usar XPath
        # Há dois links com href cupons-de-descontos: um ícone (sem texto) e o nome da loja
        store_name = ""
        try:
            store_links = card.find_elements(By.XPATH, SEL_CARD_STORE_XPATH)
            for link in store_links:
                text = link.text.strip()
                if text:
                    store_name = text
                    break
        except NoSuchElementException:
            pass

        # Temperatura (grau de promoção)
        temperature = ""
        try:
            temp_el = card.find_element(By.CSS_SELECTOR, SEL_CARD_TEMPERATURE)
            temperature = temp_el.text.strip()
        except NoSuchElementException:
            pass

        if not title or not deal_url:
            return None

        return PelandoDeal(
            title=title,
            price=price,
            image_url=image_url,
            temperature=temperature,
            store_name=store_name,
            deal_url=deal_url,
        )

    except Exception as e:
        logger.debug(f"Erro ao extrair deal: {e}")
        return None


def get_deals(driver, store_filter: str | None = None) -> list[PelandoDeal]:
    """
    Extrai deals do Pelando na aba "Recentes".

    Args:
        driver: WebDriver do Selenium
        store_filter: Nome da loja para filtrar (ex: "Mercado Livre").
                      Se None, retorna apenas lojas suportadas.

    Returns:
        Lista de PelandoDeal (máximo MAX_DEALS_TO_PROCESS)
    """
    logger.info("Navegando para Pelando...")

    driver.get(config.PELANDO_URL)
    time.sleep(3)

    # Clicar no filtro "Recentes" para ver promoções mais recentes
    try:
        recents_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SEL_FILTER_RECENTS))
        )
        recents_btn.click()
        logger.info("Clicou no filtro 'Recentes'")
        time.sleep(2)
    except TimeoutException:
        logger.warning("Filtro 'Recentes' não encontrado, continuando na página atual")

    # Aguardar cards carregarem
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SEL_DEAL_CARD))
        )
    except TimeoutException:
        logger.error("Timeout ao carregar cards do Pelando")
        return []

    deals = []
    supported_stores = get_supported_stores()
    processed_urls = set()

    cards = driver.find_elements(By.CSS_SELECTOR, SEL_DEAL_CARD)
    logger.info(f"Total de cards visíveis: {len(cards)}")

    for card in cards:
        # Limitar quantidade de deals processados
        if len(deals) >= MAX_DEALS_TO_PROCESS:
            logger.info(f"Limite de {MAX_DEALS_TO_PROCESS} deals atingido")
            break

        deal = _extract_deal_data(card)
        if not deal or deal.deal_url in processed_urls:
            continue

        processed_urls.add(deal.deal_url)

        # Filtrar por loja específica ou lojas suportadas
        if store_filter:
            if deal.store_name != store_filter:
                continue
        else:
            if deal.store_name not in supported_stores:
                continue

        logger.info(
            f"Deal encontrado: {deal.title[:40]}... | {deal.price} | {deal.store_name} | {deal.temperature}"
        )
        deals.append(deal)

    if deals:
        logger.info(f"Encontrados {len(deals)} deals de lojas suportadas")
    else:
        logger.warning("Nenhum deal de lojas suportadas encontrado")

    return deals


def scrape_pelando(driver) -> list:
    """
    Scrape principal do Pelando.
    Extrai deals e processa usando o handler de cada loja.

    Returns:
        Lista de Products processados
    """
    from models.product import Product
    from database import db

    logger.info("=" * 60)
    logger.info("Iniciando scrape do Pelando")
    logger.info("=" * 60)

    deals = get_deals(driver)

    if not deals:
        logger.info("Nenhum deal encontrado")
        return []

    products = []
    errors = 0
    skipped = 0

    for deal in deals:
        try:
            # Verificar se deal já foi processado (ANTES de chamar handler)
            if db.is_deal_processed(deal.deal_url):
                logger.debug(f"Deal já processado: {deal.title[:40]}...")
                skipped += 1
                continue

            handler = get_handler(deal.store_name)
            if not handler:
                logger.warning(f"Sem handler para loja: {deal.store_name}")
                continue

            logger.info(f"Processando deal via {handler.display_name}: {deal.title[:40]}...")

            product = handler.process_deal(driver, deal)

            if product:
                products.append(product)
                # Marcar deal como processado
                db.mark_deal_processed(deal.deal_url)
                logger.info(f"Produto processado: {product.mlb_id}")
            else:
                errors += 1
                logger.warning(f"Falha ao processar deal: {deal.title[:40]}")

        except Exception as e:
            errors += 1
            logger.error(f"Erro ao processar deal: {e}")

    logger.info(
        f"Scrape concluído: {len(products)} novos, {skipped} pulados, {errors} erros"
    )
    return products
