import logging
import re
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from scraper.stores.base_store import BaseStore
from models.pelando_deal import PelandoDeal
from models.product import Product

logger = logging.getLogger("AMAZON_STORE")

# Seletores Amazon SiteStripe (barra de afiliados)
SEL_GET_LINK_BTN = "#amzn-ss-get-link-button"
SEL_SHORT_LINK_TEXTAREA = "#amzn-ss-text-shortlink-textarea"

# Seletores página do produto Amazon
SEL_PRODUCT_TITLE = "#productTitle"
SEL_PRICE_WHOLE = "span.a-price-whole"
SEL_PRICE_FRACTION = "span.a-price-fraction"
SEL_ORIGINAL_PRICE = "span.a-price[data-a-strike] span.a-offscreen"
SEL_PRODUCT_IMAGE = "#landingImage"
SEL_RATING = "span.a-icon-alt"
SEL_COUPON_BADGE = "#couponBadgeRegularVpc"


class AmazonStore(BaseStore):
    name = "amazon"
    display_name = "Amazon"
    domain_url = "https://www.amazon.com.br"
    login_url = "https://associados.amazon.com.br"

    def process_deal(self, driver, deal: PelandoDeal) -> Product | None:
        """
        Processa um deal do Pelando que é da Amazon.
        1. Navega para a página do deal no Pelando
        2. Clica no botão para ir à Amazon
        3. Na página do produto, clica em "Obter Link" (SiteStripe)
        4. Extrai short link do textarea
        5. Extrai dados do produto
        6. Retorna Product
        """
        try:
            logger.info(f"Processando deal Amazon: {deal.title[:50]}...")

            # 1. Navegar para página do deal no Pelando
            driver.get(deal.deal_url)
            time.sleep(2)

            # 2. Clicar no botão para ir à Amazon
            try:
                store_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".store-link-button"))
                )

                btn_text = store_btn.text.strip().lower()
                if "cupom" in btn_text:
                    logger.info(f"Deal é cupom (botão: '{store_btn.text.strip()}'), ignorando")
                    return None

                store_btn.click()
                logger.info("Clicou no botão para ir à Amazon")
            except TimeoutException:
                logger.error("Botão store-link-button não encontrado")
                return None

            # Aguardar nova aba
            time.sleep(3)

            # Trocar para nova aba
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                logger.info("Trocou para nova aba da Amazon")

            current_url = driver.current_url
            logger.info(f"URL atual: {current_url}")

            # Verificar se chegou na Amazon
            if "amazon.com" not in current_url:
                logger.error(f"Não chegou na Amazon, URL: {current_url}")
                self._close_extra_tabs(driver)
                return None

            # 3. Aguardar página carregar
            time.sleep(3)

            # 4. Gerar link de afiliado via SiteStripe
            affiliate_link = self._generate_affiliate_link(driver)

            if not affiliate_link:
                logger.warning("Não conseguiu gerar link de afiliado Amazon")
                self._close_extra_tabs(driver)
                return None

            # 5. Extrair dados do produto
            product_data = self._extract_product_data(driver, current_url)

            if not product_data:
                logger.error("Falha ao extrair dados do produto Amazon")
                self._close_extra_tabs(driver)
                return None

            # 6. Montar Product
            product = Product(
                mlb_id=product_data["product_id"],
                title=product_data["title"],
                price=product_data["price"],
                image_url=product_data["image_url"],
                affiliate_link=affiliate_link,
                original_price=product_data.get("original_price", ""),
                coupon=product_data.get("coupon", ""),
                rating=product_data.get("rating", ""),
                temperature=deal.temperature,
                source="pelando",
                store="amazon",
            )

            logger.info(
                f"Produto Amazon processado: {product.mlb_id} | {product.title[:40]} | "
                f"{product.price} | Link: {product.affiliate_link}"
            )

            # 7. Fechar aba extra
            self._close_extra_tabs(driver)

            return product

        except Exception as e:
            logger.error(f"Erro ao processar deal Amazon: {e}")
            self._close_extra_tabs(driver)
            return None

    def is_logged_in(self, driver) -> bool:
        """Verifica se está logado no Amazon Associates (SiteStripe visível)."""
        try:
            driver.get("https://www.amazon.com.br")
            time.sleep(3)
            # SiteStripe aparece como barra no topo quando logado
            sitestripe = driver.find_elements(By.CSS_SELECTOR, "#amzn-ss-wrap")
            logged_in = len(sitestripe) > 0
            if logged_in:
                logger.info("Logado no Amazon Associates (SiteStripe visível)")
            else:
                logger.warning("Não logado no Amazon Associates")
            return logged_in
        except Exception as e:
            logger.error(f"Erro ao verificar login Amazon: {e}")
            return False

    def login(self, driver) -> bool:
        """Login manual no Amazon Associates."""
        driver.get(self.login_url)
        time.sleep(2)

        print("\n" + "=" * 60)
        print("FAÇA LOGIN NO AMAZON ASSOCIATES NO NAVEGADOR QUE ABRIU")
        print("Após fazer login, pressione ENTER aqui no terminal...")
        print("=" * 60 + "\n")
        input()

        return self.is_logged_in(driver)

    def _generate_affiliate_link(self, driver) -> str:
        """Clica em 'Obter Link' e extrai o short link do textarea."""
        try:
            # Clicar no botão "Obter Link"
            get_link_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, SEL_GET_LINK_BTN))
            )
            get_link_btn.click()
            logger.info("Clicou em 'Obter Link'")
            time.sleep(2)

            # Extrair link do textarea
            textarea = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_SHORT_LINK_TEXTAREA))
            )
            short_link = textarea.get_attribute("value") or textarea.text
            short_link = short_link.strip()

            if short_link and "amzn.to" in short_link:
                logger.info(f"Link de afiliado gerado: {short_link}")
                return short_link
            else:
                logger.warning(f"Link inesperado no textarea: {short_link}")
                return short_link if short_link else ""

        except TimeoutException:
            logger.error("Timeout ao gerar link de afiliado Amazon")
            return ""
        except Exception as e:
            logger.error(f"Erro ao gerar link de afiliado Amazon: {e}")
            return ""

    def _extract_product_data(self, driver, url: str) -> dict | None:
        """Extrai dados do produto da página da Amazon."""
        try:
            # ID do produto (ASIN)
            product_id = self._extract_asin(url)

            # Título
            title = ""
            try:
                title_el = driver.find_element(By.CSS_SELECTOR, SEL_PRODUCT_TITLE)
                title = title_el.text.strip()
            except NoSuchElementException:
                pass

            if not title:
                logger.warning("Título do produto não encontrado")
                return None

            # Preço atual
            price = self._extract_price(driver)

            # Preço original (riscado)
            original_price = self._extract_original_price(driver)

            # Imagem
            image_url = ""
            try:
                img_el = driver.find_element(By.CSS_SELECTOR, SEL_PRODUCT_IMAGE)
                image_url = img_el.get_attribute("src") or ""
            except NoSuchElementException:
                pass

            # Rating
            rating = ""
            try:
                rating_el = driver.find_element(By.CSS_SELECTOR, SEL_RATING)
                rating_text = rating_el.text.strip()
                match = re.search(r"([\d,\.]+)", rating_text)
                if match:
                    rating = match.group(1)
            except NoSuchElementException:
                pass

            # Cupom
            coupon = ""
            try:
                coupon_el = driver.find_element(By.CSS_SELECTOR, SEL_COUPON_BADGE)
                coupon = coupon_el.text.strip()
            except NoSuchElementException:
                pass

            return {
                "product_id": product_id,
                "title": title,
                "price": price,
                "original_price": original_price,
                "image_url": image_url,
                "rating": rating,
                "coupon": coupon,
            }

        except Exception as e:
            logger.error(f"Erro ao extrair dados do produto: {e}")
            return None

    def _extract_asin(self, url: str) -> str:
        """Extrai o ASIN da URL da Amazon."""
        match = re.search(r"/dp/([A-Z0-9]{10})", url)
        if match:
            return match.group(1)
        match = re.search(r"/gp/product/([A-Z0-9]{10})", url)
        if match:
            return match.group(1)
        return f"AMZ{abs(hash(url)) % 10000000000}"

    def _extract_price(self, driver) -> str:
        """Extrai o preço atual do produto."""
        try:
            whole_el = driver.find_element(By.CSS_SELECTOR, SEL_PRICE_WHOLE)
            whole = whole_el.text.strip().replace(".", "").rstrip(",")
            cents = "00"
            try:
                cents_el = driver.find_element(By.CSS_SELECTOR, SEL_PRICE_FRACTION)
                cents = cents_el.text.strip()
            except NoSuchElementException:
                pass
            return f"R$ {whole},{cents}"
        except NoSuchElementException:
            # Fallback: tentar span.a-offscreen (primeiro preço visível)
            try:
                price_el = driver.find_element(By.CSS_SELECTOR, "span.a-price span.a-offscreen")
                price_text = price_el.get_attribute("textContent").strip()
                if "R$" in price_text:
                    return price_text
            except NoSuchElementException:
                pass
        return ""

    def _extract_original_price(self, driver) -> str:
        """Extrai o preço original (riscado) se existir."""
        try:
            original_el = driver.find_element(By.CSS_SELECTOR, SEL_ORIGINAL_PRICE)
            price_text = original_el.get_attribute("textContent").strip()
            if "R$" in price_text:
                return price_text
        except NoSuchElementException:
            pass
        return ""

    def _close_extra_tabs(self, driver):
        """Fecha abas extras e volta para a principal."""
        try:
            while len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except Exception as e:
            logger.warning(f"Erro ao fechar abas extras: {e}")
