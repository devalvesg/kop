import asyncio
import json
import logging

import nodriver

from models.pelando_deal import PelandoDeal
from scraper.stores import get_handler, get_supported_stores
import config

logger = logging.getLogger("PELANDO")

# Quantidade máxima de deals a processar por ciclo
MAX_DEALS_TO_PROCESS = 10


def _is_coupon_only(title: str) -> bool:
    """Verifica se o deal é APENAS um cupom sem produto (ex: 'Cupom 10% OFF na loja X').
    Deals com [CUPOM] no título são produtos normais que têm cupom de desconto, não filtrar."""
    title_lower = title.lower().strip()
    return title_lower.startswith("cupom")


async def _bypass_cloudflare_turnstile(
    tab: nodriver.Tab, max_retries: int = 25, interval: float = 2.5
) -> bool:
    """Bypass do Cloudflare Turnstile clicando no iframe do challenge via CDP.

    O verify_cf nativo do nodriver usa template matching OpenCV com imagem em inglês,
    o que falha no Pelando (português). Aqui fazemos localização DOM do iframe e
    clique direto nas coordenadas do checkbox via CDP.

    Critério de sucesso: presença dos cards reais da página (`div[data-show-author]`).
    Isso evita falsos positivos quando o iframe ainda não renderizou.
    """
    # Várias strats pra achar o iframe do Turnstile — o src varia entre managed
    # challenge, interstitial e widget embedded
    selectors = [
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="cloudflare.com"]',
        'iframe[src*="turnstile"]',
        'iframe[title*="Cloudflare"]',
        'iframe[title*="challenge"]',
        'iframe[id^="cf-chl-widget"]',
    ]
    selectors_js = json.dumps(selectors)

    for attempt in range(1, max_retries + 1):
        await tab.sleep(interval)

        raw = await tab.evaluate(
            f"""
            JSON.stringify((() => {{
                const cards = document.querySelectorAll("div[data-show-author]");
                if (cards.length > 0) return {{ cards: cards.length }};

                const selectors = {selectors_js};
                for (const sel of selectors) {{
                    const iframe = document.querySelector(sel);
                    if (iframe) {{
                        const r = iframe.getBoundingClientRect();
                        return {{
                            sel: sel,
                            x: r.left, y: r.top, w: r.width, h: r.height,
                            visible: r.width > 0 && r.height > 0,
                            src: (iframe.src || "").slice(0, 80),
                        }};
                    }}
                }}
                return {{
                    nothing: true,
                    title: document.title,
                    iframe_count: document.querySelectorAll("iframe").length,
                }};
            }})())
            """
        )
        try:
            info = json.loads(raw) if isinstance(raw, str) else {}
        except (TypeError, ValueError):
            info = {}

        if info.get("cards"):
            logger.info(
                f"Turnstile resolvido — {info['cards']} cards detectados "
                f"(tentativa {attempt})"
            )
            return True

        if info.get("sel"):
            if not info.get("visible"):
                logger.debug(f"Tentativa {attempt}: iframe {info['sel']} invisível")
                continue
            # Checkbox fica na lateral esquerda do widget (~30px), centro vertical
            click_x = info["x"] + 30
            click_y = info["y"] + info["h"] / 2
            logger.info(
                f"Turnstile tentativa {attempt}/{max_retries}: clicando "
                f"({click_x:.0f},{click_y:.0f}) via {info['sel']}"
            )
            try:
                await tab.mouse_click(click_x, click_y)
            except Exception as e:
                logger.warning(f"mouse_click falhou: {e}")
        else:
            # Nem cards, nem iframe CF — página ainda carregando ou estado desconhecido
            if attempt <= 5 or attempt % 5 == 0:
                logger.info(
                    f"Tentativa {attempt}: aguardando — title='{info.get('title', '?')}' "
                    f"iframes={info.get('iframe_count', '?')}"
                )

    logger.error(f"Turnstile não bypassado após {max_retries} tentativas")
    return False


async def get_deals(tab: nodriver.Tab, store_filter: str | None = None) -> list[PelandoDeal]:
    """
    Extrai deals do Pelando na aba "Recentes".

    Args:
        tab: Tab do nodriver
        store_filter: Nome da loja para filtrar (ex: "Mercado Livre").
                      Se None, retorna apenas lojas suportadas.

    Returns:
        Lista de PelandoDeal (máximo MAX_DEALS_TO_PROCESS)
    """
    logger.info("Navegando para Pelando (Recentes)...")

    await tab.get(config.PELANDO_URL)

    # Bypass Cloudflare Turnstile via click direto no iframe (verify_cf nativo
    # usa template match em inglês e não funciona no Pelando em português)
    bypassed = await _bypass_cloudflare_turnstile(tab)
    if not bypassed:
        await tab.save_screenshot("/tmp/pelando_cf_failed.png")
        logger.error("Cloudflare Turnstile não bypassado. Screenshot: /tmp/pelando_cf_failed.png")
        return []

    # Aguardar cards carregarem
    card = await tab.select("div[data-show-author]", timeout=45)
    if not card:
        await tab.save_screenshot("/tmp/pelando_timeout.png")
        logger.error("Timeout ao carregar cards do Pelando. Screenshot: /tmp/pelando_timeout.png")
        return []

    # Extrair dados dos cards via JavaScript (mais rápido e robusto que select_all)
    # JSON.stringify pra contornar bug do nodriver com objetos/arrays em evaluate
    deals_raw = await tab.evaluate("""
        JSON.stringify((() => {
            const cards = Array.from(document.querySelectorAll("div[data-show-author]"));
            return cards.map(card => {
                const titleEl = card.querySelector("h3[class*='title'] a");
                const priceEl = card.querySelector("span[class*='deal-card-stamp']");
                const imgEl = card.querySelector("img[class*='deal-card-image']");
                const tempEl = card.querySelector("div[class*='deal-card-temperature'] span");
                const storeLinks = Array.from(card.querySelectorAll("a[href*='/cupons-de-descontos/']"));
                const storeName = storeLinks.find(l => l.textContent.trim())?.textContent.trim() || "";
                const isExpired = titleEl?.getAttribute("data-inactive") === "true"
                    || !!card.querySelector("[class*='inactive-label']");
                return {
                    title: titleEl?.textContent.trim() || "",
                    deal_url: titleEl?.href || "",
                    price: priceEl?.textContent.replace(/\\n/g, " ").trim() || "",
                    image_url: imgEl?.src || "",
                    temperature: tempEl?.textContent.trim() || "",
                    store_name: storeName,
                    is_expired: isExpired,
                };
            });
        })())
    """)
    try:
        deals_data = json.loads(deals_raw) if isinstance(deals_raw, str) else []
    except (TypeError, ValueError):
        deals_data = []

    if not deals_data:
        logger.warning("Nenhum card extraído via JS")
        return []

    deals = []
    supported_stores = get_supported_stores()
    processed_urls = set()

    logger.info(f"Total de cards extraídos: {len(deals_data)}")

    for d in deals_data:
        if len(deals) >= MAX_DEALS_TO_PROCESS:
            logger.info(f"Limite de {MAX_DEALS_TO_PROCESS} deals atingido")
            break

        if d.get("is_expired") or not d.get("title") or not d.get("deal_url"):
            continue

        if _is_coupon_only(d["title"]):
            logger.debug(f"Deal é cupom puro, pulando: {d['title'][:40]}")
            continue

        if d["deal_url"] in processed_urls:
            continue
        processed_urls.add(d["deal_url"])

        price = d.get("price", "")
        if price and not price.startswith("R$"):
            price = f"R$ {price}"

        deal = PelandoDeal(
            title=d["title"],
            price=price,
            image_url=d.get("image_url", ""),
            temperature=d.get("temperature", ""),
            store_name=d.get("store_name", ""),
            deal_url=d["deal_url"],
        )

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


async def scrape_pelando(tab: nodriver.Tab, logged_in_stores: set[str] | None = None) -> list:
    """
    Scrape principal do Pelando.
    Extrai deals e processa usando o handler de cada loja.

    Args:
        tab: Tab do nodriver
        logged_in_stores: Set de store names com sessão ativa.
                          Se None, processa todas as lojas.

    Returns:
        Lista de Products processados
    """
    from database import db

    logger.info("=" * 60)
    logger.info("Iniciando scrape do Pelando")
    logger.info("=" * 60)

    deals = await get_deals(tab)

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

            # Pular lojas sem sessão ativa
            if logged_in_stores is not None and handler.name not in logged_in_stores:
                logger.debug(f"Loja {handler.display_name} sem sessão ativa, pulando deal: {deal.title[:40]}")
                continue

            logger.info(f"Processando deal via {handler.display_name}: {deal.title[:40]}...")

            product = await handler.process_deal(tab, deal)

            if product:
                products.append(product)
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
