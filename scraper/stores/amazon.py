import asyncio
import json
import logging
import re

import nodriver

from scraper.stores.base_store import BaseStore
from models.pelando_deal import PelandoDeal
from models.product import Product
from config import AMAZON_AFFILIATE_TAG

logger = logging.getLogger("AMAZON_STORE")


class AmazonStore(BaseStore):
    name = "amazon"
    display_name = "Amazon"
    domain_url = "https://www.amazon.com.br"
    login_url = "https://associados.amazon.com.br"

    async def process_deal(self, tab: nodriver.Tab, deal: PelandoDeal) -> Product | None:
        """
        Processa um deal do Pelando que é da Amazon.
        1. Navega para a página do deal no Pelando
        2. Clica no botão para ir à Amazon
        3. Gera link de afiliado via ASIN + tag
        4. Extrai dados do produto
        5. Retorna Product
        """
        try:
            logger.info(f"Processando deal Amazon: {deal.title[:50]}...")

            # 1. Navegar para página do deal no Pelando
            await tab.get(deal.deal_url)
            await tab.sleep(2)

            # 2. Clicar no botão para ir à Amazon
            store_btn = await tab.select(".store-link-button", timeout=10)
            if not store_btn:
                logger.error("Botão store-link-button não encontrado")
                return None

            btn_text = (store_btn.text or "").strip().lower()
            if "cupom" in btn_text:
                logger.info(f"Deal é cupom (botão: '{btn_text}'), ignorando")
                return None

            await store_btn.click()
            logger.info("Clicou no botão para ir à Amazon")

            # Aguardar nova aba abrir
            await tab.sleep(3)

            # Pegar a nova aba (última aberta)
            browser = tab.browser
            if len(browser.tabs) < 2:
                logger.error("Nova aba não abriu após clicar no botão")
                return None

            amazon_tab = browser.tabs[-1]
            await amazon_tab  # atualizar estado interno
            current_url = amazon_tab.url
            logger.info(f"URL atual: {current_url}")

            # Verificar se chegou na Amazon
            if "amazon.com" not in current_url:
                logger.error(f"Não chegou na Amazon, URL: {current_url}")
                await self._close_extra_tabs(tab)
                return None

            # 3. Aguardar página carregar
            await amazon_tab.sleep(3)

            # 4. Gerar link de afiliado via ASIN + tag
            await amazon_tab  # atualizar URL após possíveis redirects
            affiliate_link = self._generate_affiliate_link(amazon_tab.url)

            if not affiliate_link:
                logger.warning("Não conseguiu gerar link de afiliado Amazon")
                await self._close_extra_tabs(tab)
                return None

            # 5. Extrair dados do produto
            product_data = await self._extract_product_data(amazon_tab, amazon_tab.url)

            if not product_data:
                logger.error("Falha ao extrair dados do produto Amazon")
                await self._close_extra_tabs(tab)
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
            await self._close_extra_tabs(tab)

            return product

        except Exception as e:
            logger.error(f"Erro ao processar deal Amazon: {e}")
            await self._close_extra_tabs(tab)
            return None

    async def is_logged_in(self, browser: nodriver.Browser) -> bool:
        """Verifica se está logado no Amazon Associates (SiteStripe visível)."""
        try:
            check_tab = await browser.get("https://www.amazon.com.br", new_tab=True)
            await check_tab.sleep(3)

            sitestripe = await check_tab.select("#amzn-ss-wrap", timeout=5)
            logged_in = sitestripe is not None

            if logged_in:
                logger.info("Logado no Amazon Associates (SiteStripe visível)")
            else:
                logger.warning("Não logado no Amazon Associates")

            await check_tab.close()
            return logged_in
        except Exception as e:
            logger.error(f"Erro ao verificar login Amazon: {e}")
            return False

    async def login(self, browser: nodriver.Browser) -> bool:
        """Login manual no Amazon Associates."""
        login_tab = await browser.get(self.login_url, new_tab=True)
        await login_tab.sleep(2)

        print("\n" + "=" * 60)
        print("FAÇA LOGIN NO AMAZON ASSOCIATES NO NAVEGADOR QUE ABRIU")
        print("Após fazer login, pressione ENTER aqui no terminal...")
        print("=" * 60 + "\n")
        await asyncio.get_event_loop().run_in_executor(None, input)

        await login_tab.close()
        return await self.is_logged_in(browser)

    def _generate_affiliate_link(self, url: str) -> str:
        """Constrói link limpo de afiliado a partir do ASIN + tag."""
        try:
            asin = self._extract_asin(url)
            if not asin:
                logger.error(f"ASIN não encontrado na URL: {url}")
                return ""
            affiliate_link = f"https://www.amazon.com.br/dp/{asin}?tag={AMAZON_AFFILIATE_TAG}"
            logger.info(f"Link de afiliado gerado: {affiliate_link}")
            return affiliate_link
        except Exception as e:
            logger.error(f"Erro ao gerar link de afiliado Amazon: {e}")
            return ""

    async def _extract_product_data(self, tab: nodriver.Tab, url: str) -> dict | None:
        """Extrai dados do produto da página da Amazon via JavaScript."""
        try:
            product_id = self._extract_asin(url)

            data_raw = await tab.evaluate("""
                JSON.stringify((() => {
                    const title = document.querySelector('#productTitle')?.textContent?.trim() || '';

                    // Preço
                    const whole = document.querySelector('span.a-price-whole')?.textContent?.trim()?.replace('.', '')?.replace(',', '') || '';
                    const fraction = document.querySelector('span.a-price-fraction')?.textContent?.trim() || '00';
                    let price = '';
                    if (whole) {
                        price = 'R$ ' + whole.replace(/,$/, '') + ',' + fraction;
                    } else {
                        const offscreen = document.querySelector('span.a-price span.a-offscreen');
                        if (offscreen) price = offscreen.textContent?.trim() || '';
                    }

                    // Preço original (riscado)
                    let originalPrice = '';
                    const origEl = document.querySelector('span.a-price[data-a-strike] span.a-offscreen');
                    if (origEl) {
                        const t = origEl.textContent?.trim() || '';
                        if (t.includes('R$')) originalPrice = t;
                    }

                    // Imagem
                    const imgEl = document.querySelector('#landingImage');
                    const imageUrl = imgEl?.src || '';

                    // Rating
                    let rating = '';
                    const ratingEl = document.querySelector('span.a-icon-alt');
                    if (ratingEl) {
                        const m = ratingEl.textContent.match(/([\\d,\\.]+)/);
                        if (m) rating = m[1];
                    }

                    // Cupom
                    const couponEl = document.querySelector('#couponBadgeRegularVpc');
                    const coupon = couponEl?.textContent?.trim() || '';

                    return { title, price, originalPrice, imageUrl, rating, coupon };
                })())
            """)
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else None
            except (TypeError, ValueError):
                data = None

            if not data or not data.get("title"):
                logger.warning("Título do produto não encontrado")
                return None

            return {
                "product_id": product_id,
                "title": data["title"],
                "price": data.get("price", ""),
                "original_price": data.get("originalPrice", ""),
                "image_url": data.get("imageUrl", ""),
                "rating": data.get("rating", ""),
                "coupon": data.get("coupon", ""),
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

    async def _close_extra_tabs(self, main_tab: nodriver.Tab):
        """Fecha abas extras e volta para a principal."""
        try:
            browser = main_tab.browser
            for t in browser.tabs[:]:
                if t != main_tab:
                    try:
                        await t.close()
                    except Exception:
                        pass
            await main_tab.bring_to_front()
        except Exception as e:
            logger.warning(f"Erro ao fechar abas extras: {e}")
