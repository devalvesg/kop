import logging
import re
import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from scraper.stores.base_store import BaseStore
from models.pelando_deal import PelandoDeal
from models.product import Product
import config

logger = logging.getLogger("ML_STORE")

# Seletores CSS para página do produto no ML
SEL_PRODUCT_TITLE = "h1.ui-pdp-title"
SEL_PRODUCT_PRICE = "span.andes-money-amount__fraction"
SEL_PRODUCT_CENTS = "span.andes-money-amount__cents"
SEL_PRODUCT_IMAGE = "img.ui-pdp-image"
SEL_PRODUCT_RATING = "span.ui-pdp-review__rating"
SEL_PRODUCT_SALES = "span.ui-pdp-subtitle"
# Preço original (antes do desconto) - elemento <s> com classe andes-money-amount--previous
SEL_ORIGINAL_PRICE = "s.andes-money-amount--previous"
SEL_ORIGINAL_PRICE_FRACTION = "s.andes-money-amount--previous .andes-money-amount__fraction"
SEL_ORIGINAL_PRICE_CENTS = "s.andes-money-amount--previous .andes-money-amount__cents"

# Cupom disponível na página do produto
SEL_COUPON_LABEL = "#coupon-awareness-row-label"

# Seletor para landing page do ML (após redirect do Pelando)
# Essa landing é exclusiva do ML, outras lojas vão direto pro produto
SEL_GO_TO_PRODUCT_BTN = "a.poly-component__link--action-link"

# Seletores para barra de afiliados
SEL_GENERATE_LINK_BTN = "button.generate_link_button"
SEL_LINK_TEXTAREA = "textarea.andes-form-control__field"
SEL_COPY_LINK_BTN = "button.textfield-link__button"
SEL_AFFILIATE_MODAL = "div.andes-modal__content"


class MercadoLivreStore(BaseStore):
    name = "mercado_livre"
    display_name = "Mercado Livre"

    def process_deal(self, driver, deal: PelandoDeal) -> Product | None:
        """
        Processa um deal do Pelando que é do Mercado Livre.
        1. Navega para a página do deal no Pelando
        2. Clica no botão para ir ao ML
        3. Na página do produto, gera link de afiliado
        4. Extrai dados do produto
        5. Retorna Product
        """
        try:
            logger.info(f"Processando deal ML: {deal.title[:50]}...")

            # 1. Navegar para página do deal no Pelando
            driver.get(deal.deal_url)
            time.sleep(2)

            # 2. Verificar e clicar no botão "store-link-button" para ir ao ML
            try:
                store_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".store-link-button"))
                )

                # Verificar se é cupom (botão "Pegar Cupom" ao invés de "Ir para loja")
                btn_text = store_btn.text.strip().lower()
                if "cupom" in btn_text:
                    logger.info(f"Deal é cupom (botão: '{store_btn.text.strip()}'), ignorando")
                    return None

                store_btn.click()
                logger.info("Clicou no botão para ir ao ML")
            except TimeoutException:
                logger.error("Botão store-link-button não encontrado")
                return None

            # Aguardar nova aba ou redirecionamento
            time.sleep(3)

            # Verificar se abriu nova aba
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                logger.info("Trocou para nova aba do ML")

            # 3. Aguardar carregar página do ML (short links mercadolivre.com/sec/ redirecionam)
            current_url = driver.current_url
            logger.info(f"URL atual: {current_url}")

            time.sleep(2)

            # Se não estiver no ML, algo deu errado
            if "mercadolivre.com" not in current_url:
                logger.error(f"Não chegou no ML, URL: {current_url}")
                self._close_extra_tabs(driver)
                return None

            # 3.1 Se estiver na landing page (/social/pelando), clicar em "Ir para produto"
            if "/social/" in current_url:
                logger.info("Detectada landing page do ML, clicando em 'Ir para produto'...")
                try:
                    go_to_product_btn = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, SEL_GO_TO_PRODUCT_BTN))
                    )
                    go_to_product_btn.click()
                    time.sleep(3)
                    current_url = driver.current_url
                    logger.info(f"Navegou para página do produto: {current_url}")
                except TimeoutException:
                    logger.error("Botão 'Ir para produto' não encontrado na landing page")
                    self._close_extra_tabs(driver)
                    return None

            # 4. Aguardar barra de afiliados carregar e gerar link
            time.sleep(2)
            affiliate_link = self._generate_affiliate_link(driver)

            if not affiliate_link:
                logger.warning("Não conseguiu gerar link de afiliado, usando URL direta")
                affiliate_link = current_url

            # 5. Extrair dados do produto
            product_data = self._extract_product_data(driver, deal)

            if not product_data:
                logger.error("Falha ao extrair dados do produto")
                self._close_extra_tabs(driver)
                return None

            product = Product(
                mlb_id=product_data["mlb_id"],
                title=product_data["title"],
                price=product_data["price"],
                image_url=product_data["image_url"],
                affiliate_link=affiliate_link,
                original_price=product_data.get("original_price", ""),
                coupon=product_data.get("coupon", ""),
                rating=product_data.get("rating", ""),
                sales_info=product_data.get("sales_info", ""),
                temperature=deal.temperature,
                source="pelando",
            )

            logger.info(f"Produto extraído: {product.title[:50]} - {product.price}")

            # Fechar abas extras e voltar para principal
            self._close_extra_tabs(driver)

            return product

        except Exception as e:
            logger.error(f"Erro ao processar deal ML: {e}")
            self._close_extra_tabs(driver)
            return None

    def _generate_affiliate_link(self, driver) -> str:
        """Gera link de afiliado usando a barra de afiliados do ML."""
        try:
            # Aguardar botão de gerar link
            generate_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, SEL_GENERATE_LINK_BTN))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", generate_btn)
            time.sleep(0.5)
            generate_btn.click()
            logger.info("Clicou em 'Gerar link'")

            time.sleep(2)

            # Tentar pegar link do textarea
            try:
                textarea = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, SEL_LINK_TEXTAREA))
                )
                affiliate_link = textarea.get_attribute("value") or textarea.text
                if affiliate_link:
                    logger.info(f"Link de afiliado obtido: {affiliate_link[:60]}...")
                    return affiliate_link
            except TimeoutException:
                pass

            # Fallback: tentar capturar via clipboard
            try:
                copy_btn = driver.find_element(By.CSS_SELECTOR, SEL_COPY_LINK_BTN)
                driver.execute_script("""
                    window.__copiedText = '';
                    const originalWriteText = navigator.clipboard.writeText;
                    navigator.clipboard.writeText = function(text) {
                        window.__copiedText = text;
                        return originalWriteText.call(navigator.clipboard, text);
                    };
                """)
                copy_btn.click()
                time.sleep(1)
                affiliate_link = driver.execute_script("return window.__copiedText || '';")
                if affiliate_link:
                    logger.info(f"Link via clipboard: {affiliate_link[:60]}...")
                    return affiliate_link
            except Exception:
                pass

            logger.warning("Não conseguiu capturar link de afiliado")
            return ""

        except TimeoutException:
            logger.warning("Botão de gerar link não encontrado (usuário pode não estar logado como afiliado)")
            return ""
        except Exception as e:
            logger.error(f"Erro ao gerar link de afiliado: {e}")
            return ""

    def _extract_product_data(self, driver, deal: PelandoDeal) -> dict | None:
        """Extrai dados do produto da página do ML."""
        try:
            # Extrair MLb ID da URL
            mlb_id = self._extract_mlb_id(driver.current_url)

            # Título
            try:
                title_el = driver.find_element(By.CSS_SELECTOR, SEL_PRODUCT_TITLE)
                title = title_el.text.strip()
            except NoSuchElementException:
                title = deal.title  # Fallback para título do Pelando

            # Preço atual - usar meta tag (mais confiável, não confunde com preço original)
            price = ""
            try:
                meta_price = driver.find_element(By.CSS_SELECTOR, 'meta[itemprop="price"]')
                price_value = meta_price.get_attribute("content")  # ex: "34.30"
                if price_value:
                    price = f"R$ {price_value.replace('.', ',')}"
                    logger.info(f"Preço via meta tag: {price}")
            except NoSuchElementException:
                pass

            if not price:
                # Fallback: seletor CSS (pegar o que NÃO está dentro do <s>)
                try:
                    price_text = driver.execute_script("""
                        var fractions = document.querySelectorAll('span.andes-money-amount__fraction');
                        for (var f of fractions) {
                            if (!f.closest('s')) {
                                var parent = f.closest('.andes-money-amount');
                                var cents = parent ? parent.querySelector('.andes-money-amount__cents') : null;
                                return f.textContent + '|' + (cents ? cents.textContent : '00');
                            }
                        }
                        return null;
                    """)
                    if price_text:
                        parts = price_text.split("|")
                        price = f"R$ {parts[0]},{parts[1]}"
                except Exception:
                    price = deal.price  # Fallback para preço do Pelando

            if not price:
                price = deal.price

            # Preço original (antes do desconto)
            original_price = ""
            try:
                original_el = driver.find_element(By.CSS_SELECTOR, SEL_ORIGINAL_PRICE)
                aria_label = original_el.get_attribute("aria-label") or ""
                # aria-label: "Antes: 117 reais com 07 centavos"
                match = re.search(r"(\d[\d.]*)\s*reais?\s*com\s*(\d+)\s*centavos?", aria_label)
                if match:
                    fraction = match.group(1).replace(".", "")
                    cents = match.group(2)
                    original_price = f"R$ {fraction},{cents}"
                else:
                    # Fallback: usar seletores CSS
                    original_fraction_el = driver.find_element(By.CSS_SELECTOR, SEL_ORIGINAL_PRICE_FRACTION)
                    original_fraction = original_fraction_el.text.strip()
                    try:
                        original_cents_el = driver.find_element(By.CSS_SELECTOR, SEL_ORIGINAL_PRICE_CENTS)
                        original_cents = original_cents_el.text.strip()
                        original_price = f"R$ {original_fraction},{original_cents}"
                    except NoSuchElementException:
                        original_price = f"R$ {original_fraction},00"

                # Validação: descartar se preço original == preço atual
                if original_price and original_price == price:
                    logger.info(f"Preço original ({original_price}) igual ao atual, descartando")
                    original_price = ""
                elif original_price:
                    logger.info(f"Preço original encontrado: {original_price}")
            except NoSuchElementException:
                logger.debug("Preço original não encontrado (produto pode não ter desconto)")

            # Imagem - tentar pegar a melhor resolução disponível
            image_url = ""
            try:
                # 1. Tentar og:image (geralmente boa qualidade)
                og_img = driver.find_elements(By.CSS_SELECTOR, 'meta[property="og:image"]')
                if og_img:
                    image_url = og_img[0].get_attribute("content") or ""

                # 2. Fallback: img.ui-pdp-image (data-zoom > src)
                if not image_url:
                    image_el = driver.find_element(By.CSS_SELECTOR, SEL_PRODUCT_IMAGE)
                    image_url = image_el.get_attribute("data-zoom") or image_el.get_attribute("src") or ""

                # Remover query params de resize
                if "?" in image_url:
                    image_url = image_url.split("?")[0]

                # Converter para alta resolução:
                # D_Q_NP → D_NQ_NP (sem compressão de qualidade)
                # sufixo -R (Reduced) → -O (Original)
                if "mlstatic.com" in image_url:
                    image_url = image_url.replace("/D_Q_NP_", "/D_NQ_NP_")
                    image_url = re.sub(r"-R(\.\w+)$", r"-O\1", image_url)

                logger.info(f"URL da imagem: {image_url[:100]}...")
            except NoSuchElementException:
                image_url = deal.image_url  # Fallback

            # Rating (opcional)
            rating = ""
            try:
                rating_el = driver.find_element(By.CSS_SELECTOR, SEL_PRODUCT_RATING)
                rating = rating_el.text.strip()
            except NoSuchElementException:
                pass

            # Info de vendas (opcional)
            sales_info = ""
            try:
                sales_el = driver.find_element(By.CSS_SELECTOR, SEL_PRODUCT_SALES)
                sales_text = sales_el.text.strip()
                if "vendido" in sales_text.lower():
                    sales_info = sales_text
            except NoSuchElementException:
                pass

            # Cupom disponível (opcional)
            coupon = ""
            try:
                coupon_text = driver.execute_script("""
                    var label = document.querySelector('#coupon-awareness-row-label');
                    if (label) return label.textContent.trim();
                    return null;
                """)
                if coupon_text:
                    # Parse "Aplicar R$5 OFF." ou "Aplicar 10% OFF."
                    match = re.search(r'Aplicar\s+(R\$\s*[\d.,]+|[\d.,]+%)\s*OFF', coupon_text)
                    if match:
                        coupon = match.group(1).strip() + " OFF"
                        logger.info(f"Cupom encontrado: {coupon}")
            except Exception:
                pass

            return {
                "mlb_id": mlb_id,
                "title": title,
                "price": price,
                "original_price": original_price,
                "coupon": coupon,
                "image_url": image_url,
                "rating": rating,
                "sales_info": sales_info,
            }

        except Exception as e:
            logger.error(f"Erro ao extrair dados do produto: {e}")
            return None

    def _extract_mlb_id(self, url: str) -> str:
        """Extrai o MLB ID da URL do produto."""
        # Padrão: MLB-1234567890 ou MLB1234567890
        match = re.search(r"MLB-?(\d+)", url, re.IGNORECASE)
        if match:
            return f"MLB{match.group(1)}"
        # Fallback: usar hash da URL
        return f"MLB{abs(hash(url)) % 10000000000}"

    def _resolve_short_link(self, url: str) -> str:
        """Resolve short link do ML seguindo redirects via requests."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        for method in (requests.head, requests.get):
            try:
                resp = method(url, allow_redirects=True, timeout=15, headers=headers)
                resolved = resp.url
                logger.info(f"Short link resolvido ({method.__name__}): {resolved[:100]}")
                if "mercadolivre.com.br" in resolved:
                    return resolved
            except Exception as e:
                logger.warning(f"Erro {method.__name__} ao resolver short link: {e}")
        return ""

    def _close_extra_tabs(self, driver):
        """Fecha abas extras e volta para a principal."""
        try:
            while len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except Exception:
            pass

    def is_logged_in(self, driver) -> bool:
        """Verifica se está logado no programa de afiliados do ML."""
        try:
            driver.get(config.ML_HUB_URL)
            time.sleep(3)
            current_url = driver.current_url
            return "login" not in current_url and "afiliados" in current_url
        except Exception:
            return False

    def login(self, driver) -> bool:
        """Realiza login no ML (redireciona para login manual)."""
        try:
            driver.get("https://www.mercadolivre.com.br/navigation/login")
            print("\n" + "=" * 60)
            print("FAÇA LOGIN NO MERCADO LIVRE NO NAVEGADOR")
            print("Após fazer login, pressione ENTER aqui...")
            print("=" * 60 + "\n")
            input()
            return self.is_logged_in(driver)
        except Exception:
            return False
