import asyncio
import logging
import re
import requests

import nodriver

from scraper.stores.base_store import BaseStore
from models.pelando_deal import PelandoDeal
from models.product import Product

logger = logging.getLogger("ML_STORE")


class MercadoLivreStore(BaseStore):
    name = "mercado_livre"
    display_name = "Mercado Livre"
    domain_url = "https://www.mercadolivre.com.br"
    login_url = "https://www.mercadolivre.com.br/navigation/login"

    async def process_deal(self, tab: nodriver.Tab, deal: PelandoDeal) -> Product | None:
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
            await tab.get(deal.deal_url)
            await tab.sleep(2)

            # 2. Clicar no botão para ir ao ML
            store_btn = await tab.select(".store-link-button", timeout=10)
            if not store_btn:
                logger.error("Botão store-link-button não encontrado")
                return None

            btn_text = (store_btn.text or "").strip().lower()
            if "cupom" in btn_text:
                logger.info(f"Deal é cupom (botão: '{btn_text}'), ignorando")
                return None

            await store_btn.click()
            logger.info("Clicou no botão para ir ao ML")

            # Aguardar nova aba
            await tab.sleep(3)

            # Pegar a nova aba
            browser = tab.browser
            if len(browser.tabs) < 2:
                logger.error("Nova aba não abriu após clicar no botão")
                return None

            ml_tab = browser.tabs[-1]
            await ml_tab  # atualizar estado
            current_url = ml_tab.url
            logger.info(f"URL atual: {current_url}")

            # Se for short link, aguardar redirect
            if "mercadolivre.com/sec/" in current_url:
                short_link_url = current_url
                logger.info("Short link detectado, aguardando browser resolver redirect...")

                # Camada 1: Aguardar browser resolver
                resolved = False
                for i in range(15):
                    await ml_tab.sleep(2)
                    await ml_tab
                    current_url = ml_tab.url
                    if "mercadolivre.com.br" in current_url:
                        logger.info(f"Browser resolveu redirect ({(i+1)*2}s): {current_url[:80]}")
                        resolved = True
                        break
                    logger.debug(f"Aguardando redirect... ({i+1}/15) URL: {current_url[:80]}")

                # Camada 2: Extrair URL de redirect do page source
                if not resolved:
                    logger.warning("Browser não resolveu, extraindo URL da página...")
                    page_content = await ml_tab.get_content()
                    redirect_url = self._extract_redirect_from_html(page_content)
                    if redirect_url:
                        logger.info(f"URL extraída da página: {redirect_url[:80]}")
                        await ml_tab.get(redirect_url)
                        await ml_tab.sleep(2)
                        await ml_tab
                        current_url = ml_tab.url
                        resolved = "mercadolivre.com.br" in current_url

                # Camada 3: Resolver via HTTP (cloudscraper/requests)
                if not resolved:
                    logger.warning("Tentando resolver short link via HTTP...")
                    resolved_url = self._resolve_short_link(short_link_url)
                    if resolved_url and "mercadolivre.com.br" in resolved_url:
                        logger.info(f"Resolvido via HTTP: {resolved_url[:200]}")
                        await ml_tab.get(resolved_url)
                        await ml_tab.sleep(2)
                        await ml_tab
                        current_url = ml_tab.url
                        resolved = "mercadolivre.com.br" in current_url

                if not resolved:
                    logger.error(f"Todas as tentativas falharam para short link: {short_link_url}")

            # Se não estiver no ML, algo deu errado
            if "mercadolivre.com.br" not in current_url:
                logger.error(f"Não chegou no ML, URL: {current_url}")
                await self._close_extra_tabs(tab)
                return None

            # 3.1 Se estiver na landing page (/social/pelando), clicar em "Ir para produto"
            if "/social/" in current_url:
                logger.info("Detectada landing page do ML, clicando em 'Ir para produto'...")
                go_btn = await ml_tab.select("a.poly-component__link--action-link", timeout=10)
                if go_btn:
                    await go_btn.click()
                    await ml_tab.sleep(3)
                    await ml_tab
                    current_url = ml_tab.url
                    logger.info(f"Navegou para página do produto: {current_url}")
                else:
                    logger.error("Botão 'Ir para produto' não encontrado na landing page")
                    await self._close_extra_tabs(tab)
                    return None

            # 4. Gerar link de afiliado
            await ml_tab.sleep(2)
            affiliate_link = await self._generate_affiliate_link(ml_tab)

            if not affiliate_link:
                logger.warning("Não conseguiu gerar link de afiliado, usando URL direta")
                affiliate_link = current_url

            # 5. Extrair dados do produto
            product_data = await self._extract_product_data(ml_tab, deal)

            if not product_data:
                logger.error("Falha ao extrair dados do produto")
                await self._close_extra_tabs(tab)
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
                store="mercado_livre",
            )

            logger.info(f"Produto extraído: {product.title[:50]} - {product.price}")

            await self._close_extra_tabs(tab)
            return product

        except Exception as e:
            logger.error(f"Erro ao processar deal ML: {e}")
            await self._close_extra_tabs(tab)
            return None

    async def _generate_affiliate_link(self, tab: nodriver.Tab) -> str:
        """Gera link de afiliado usando a barra de afiliados do ML."""
        try:
            # Aguardar botão de gerar link
            generate_btn = await tab.select("button.generate_link_button", timeout=10)
            if not generate_btn:
                logger.warning("Botão de gerar link não encontrado (usuário pode não estar logado como afiliado)")
                return ""

            await generate_btn.scroll_into_view()
            await tab.sleep(0.5)
            await generate_btn.click()
            logger.info("Clicou em 'Gerar link'")

            await tab.sleep(2)

            # Tentar pegar link do textarea via JS
            affiliate_link = await tab.evaluate("""
                (() => {
                    const textarea = document.querySelector('textarea.andes-form-control__field');
                    return textarea ? (textarea.value || textarea.textContent || '') : '';
                })()
            """)

            if affiliate_link:
                logger.info(f"Link de afiliado obtido: {str(affiliate_link)[:60]}...")
                return affiliate_link

            # Fallback: interceptar clipboard via botão copiar
            try:
                copy_btn = await tab.select("button.textfield-link__button", timeout=3)
                if copy_btn:
                    await tab.evaluate("""
                        window.__copiedText = '';
                        const orig = navigator.clipboard.writeText;
                        navigator.clipboard.writeText = function(text) {
                            window.__copiedText = text;
                            return orig.call(navigator.clipboard, text);
                        };
                    """)
                    await copy_btn.click()
                    await tab.sleep(1)
                    affiliate_link = await tab.evaluate("window.__copiedText || ''")
                    if affiliate_link:
                        logger.info(f"Link via clipboard: {str(affiliate_link)[:60]}...")
                        return affiliate_link
            except Exception:
                pass

            logger.warning("Não conseguiu capturar link de afiliado")
            return ""

        except Exception as e:
            logger.error(f"Erro ao gerar link de afiliado: {e}")
            return ""

    async def _extract_product_data(self, tab: nodriver.Tab, deal: PelandoDeal) -> dict | None:
        """Extrai dados do produto da página do ML via JavaScript."""
        try:
            await tab
            mlb_id = self._extract_mlb_id(tab.url)

            data = await tab.evaluate("""
                (() => {
                    // Título
                    const titleEl = document.querySelector('h1.ui-pdp-title');
                    const title = titleEl?.textContent?.trim() || '';

                    // Preço via meta tag (mais confiável)
                    let price = '';
                    const metaPrice = document.querySelector('meta[itemprop="price"]');
                    if (metaPrice) {
                        const val = metaPrice.getAttribute('content');
                        if (val) price = 'R$ ' + val.replace('.', ',');
                    }
                    if (!price) {
                        // Fallback: seletor CSS (pegar o que NÃO está dentro do <s>)
                        const fractions = document.querySelectorAll('span.andes-money-amount__fraction');
                        for (const f of fractions) {
                            if (!f.closest('s')) {
                                const parent = f.closest('.andes-money-amount');
                                const cents = parent ? parent.querySelector('.andes-money-amount__cents') : null;
                                price = 'R$ ' + f.textContent + ',' + (cents ? cents.textContent : '00');
                                break;
                            }
                        }
                    }

                    // Preço original (riscado) via aria-label
                    let originalPrice = '';
                    const origEl = document.querySelector('s.andes-money-amount--previous');
                    if (origEl) {
                        const aria = origEl.getAttribute('aria-label') || '';
                        const m = aria.match(/(\\d[\\d.]*)\\ *reais?\\ *com\\ *(\\d+)\\ *centavos?/);
                        if (m) {
                            originalPrice = 'R$ ' + m[1].replace('.', '') + ',' + m[2];
                        } else {
                            const frac = origEl.querySelector('.andes-money-amount__fraction');
                            const cents = origEl.querySelector('.andes-money-amount__cents');
                            if (frac) {
                                originalPrice = 'R$ ' + frac.textContent + ',' + (cents ? cents.textContent : '00');
                            }
                        }
                    }

                    // Descartar se igual ao preço atual
                    if (originalPrice && originalPrice === price) originalPrice = '';

                    // Imagem (melhor resolução)
                    let imageUrl = '';
                    const imgs = document.querySelectorAll('img.ui-pdp-image');
                    for (const img of imgs) {
                        const zoom = img.getAttribute('data-zoom') || '';
                        if (zoom && zoom.includes('mlstatic.com')) { imageUrl = zoom; break; }
                        const src = img.src || '';
                        if (src && src.includes('mlstatic.com') && !imageUrl) imageUrl = src;
                    }
                    if (!imageUrl) {
                        const og = document.querySelector('meta[property="og:image"]');
                        if (og) imageUrl = og.getAttribute('content') || '';
                    }
                    if (imageUrl && imageUrl.includes('?')) imageUrl = imageUrl.split('?')[0];

                    // Rating
                    const ratingEl = document.querySelector('span.ui-pdp-review__rating');
                    const rating = ratingEl?.textContent?.trim() || '';

                    // Vendas
                    const salesEl = document.querySelector('span.ui-pdp-subtitle');
                    const salesText = salesEl?.textContent?.trim() || '';
                    const salesInfo = salesText.toLowerCase().includes('vendido') ? salesText : '';

                    // Cupom
                    let coupon = '';
                    const couponEl = document.querySelector('#coupon-awareness-row-label');
                    if (couponEl) {
                        const ct = couponEl.textContent.trim();
                        const cm = ct.match(/Aplicar\\s+(R\\$\\s*[\\d.,]+|[\\d.,]+%)\\s*OFF/);
                        if (cm) coupon = cm[1].trim() + ' OFF';
                    }

                    return { title, price, originalPrice, imageUrl, rating, salesInfo, coupon };
                })()
            """, return_by_value=True)

            if not data or not data.get("title"):
                title = deal.title  # Fallback para título do Pelando
                if not title:
                    logger.warning("Título do produto não encontrado")
                    return None
                data = data or {}
                data["title"] = title

            # Melhorar URL da imagem (alta resolução)
            image_url = data.get("imageUrl", "")
            if "mlstatic.com" in image_url:
                image_url = image_url.replace("/D_Q_NP_", "/D_NQ_NP_")
                image_url = re.sub(r"-[RV](\.\w+)$", r"-O\1", image_url)

            return {
                "mlb_id": mlb_id,
                "title": data["title"],
                "price": data.get("price", "") or deal.price,
                "original_price": data.get("originalPrice", ""),
                "coupon": data.get("coupon", ""),
                "image_url": image_url or deal.image_url,
                "rating": data.get("rating", ""),
                "sales_info": data.get("salesInfo", ""),
            }

        except Exception as e:
            logger.error(f"Erro ao extrair dados do produto: {e}")
            return None

    def _extract_mlb_id(self, url: str) -> str:
        """Extrai o MLB ID da URL do produto."""
        match = re.search(r"MLB-?(\d+)", url, re.IGNORECASE)
        if match:
            return f"MLB{match.group(1)}"
        return f"MLB{abs(hash(url)) % 10000000000}"

    def _extract_redirect_from_html(self, html: str) -> str:
        """Extrai URL de redirect do HTML (meta refresh, JS location, etc)."""
        try:
            # Meta refresh
            match = re.search(
                r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\'>\s]+)',
                html, re.IGNORECASE
            )
            if match and "mercadolivre.com.br" in match.group(1):
                return match.group(1)

            # JS: window.location = "..."
            match = re.search(
                r'(?:window\.)?location(?:\.href)?\s*=\s*["\']([^"\']+mercadolivre\.com\.br[^"\']*)["\']',
                html
            )
            if match:
                return match.group(1)

            # JS: location.replace("...")
            match = re.search(
                r'location\.replace\s*\(\s*["\']([^"\']+mercadolivre\.com\.br[^"\']*)["\']',
                html
            )
            if match:
                return match.group(1)

            # Qualquer URL de produto ML na página
            match = re.search(
                r'(https?://[^\s"\'<>]+mercadolivre\.com\.br/[^\s"\'<>]*MLB[^\s"\'<>]*)',
                html
            )
            if match:
                return match.group(1)

            logger.debug(f"Page source (500 chars): {html[:500]}")
        except Exception as e:
            logger.warning(f"Erro ao extrair redirect da página: {e}")
        return ""

    def _resolve_short_link(self, url: str) -> str:
        """Resolve short link do ML seguindo redirects passo a passo."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # 1. Tentar com cloudscraper
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            resp = scraper.get(url, allow_redirects=True, timeout=15)
            resolved = resp.url
            logger.info(f"Short link resolvido (cloudscraper): {resolved[:150]}")
            if "mercadolivre.com.br" in resolved:
                return resolved
        except ImportError:
            logger.debug("cloudscraper não instalado, pulando")
        except Exception as e:
            logger.warning(f"Erro cloudscraper: {e}")

        # 2. Seguir redirects manualmente
        try:
            from urllib.parse import urlparse
            session = requests.Session()
            current_url = url
            for step in range(10):
                resp = session.get(current_url, allow_redirects=False, timeout=15, headers=headers)
                location = resp.headers.get("Location", "")
                logger.info(f"Redirect step {step}: HTTP {resp.status_code} -> {location[:150] if location else 'N/A'}")

                if resp.status_code in (301, 302, 303, 307, 308) and location:
                    if location.startswith("/"):
                        parsed = urlparse(current_url)
                        location = f"{parsed.scheme}://{parsed.netloc}{location}"
                    current_url = location
                    if "mercadolivre.com.br" in current_url:
                        logger.info(f"Short link resolvido (manual step {step}): {current_url[:150]}")
                        return current_url
                else:
                    break
        except Exception as e:
            logger.warning(f"Erro ao seguir redirects manualmente: {e}")

        # 3. Fallback: requests com allow_redirects=True
        for method in (requests.head, requests.get):
            try:
                resp = method(url, allow_redirects=True, timeout=15, headers=headers)
                resolved = resp.url
                logger.info(f"Short link resolvido ({method.__name__}): {resolved[:150]}")
                if "mercadolivre.com.br" in resolved:
                    return resolved
            except Exception as e:
                logger.warning(f"Erro {method.__name__} ao resolver short link: {e}")
        return ""

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
        except Exception:
            pass

    async def is_logged_in(self, browser: nodriver.Browser) -> bool:
        """Verifica se está logado no programa de afiliados do ML."""
        try:
            check_tab = await browser.get("https://www.mercadolivre.com.br/afiliados/hub", new_tab=True)
            await check_tab.sleep(3)
            await check_tab
            current_url = check_tab.url
            logged_in = "login" not in current_url and "afiliados" in current_url
            await check_tab.close()
            return logged_in
        except Exception:
            return False

    async def login(self, browser: nodriver.Browser) -> bool:
        """Realiza login no ML (redireciona para login manual)."""
        try:
            login_tab = await browser.get(self.login_url, new_tab=True)
            print("\n" + "=" * 60)
            print("FAÇA LOGIN NO MERCADO LIVRE NO NAVEGADOR QUE ABRIU")
            print("Após fazer login, pressione ENTER aqui no terminal...")
            print("=" * 60 + "\n")
            await asyncio.get_event_loop().run_in_executor(None, input)
            await login_tab.close()
            return await self.is_logged_in(browser)
        except Exception:
            return False
