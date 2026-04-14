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


async def _bypass_cloudflare_challenge(
    tab: nodriver.Tab, max_retries: int = 25, interval: float = 2.5
) -> bool:
    """Bypass do challenge do Cloudflare no Pelando.

    A página serve um interstitial simples com botão "Verify you are human"
    (não é o Turnstile widget). Localizamos o botão via DOM (sem iframe,
    sem shadow DOM) e clicamos nas coordenadas via CDP mouse_click — usar
    user gesture real ajuda a passar a verificação de automação do CF.

    Critério de sucesso: presença dos cards reais (`div[data-show-author]`).
    """
    for attempt in range(1, max_retries + 1):
        await tab.sleep(interval)

        raw = await tab.evaluate(
            """
            JSON.stringify((() => {
                const cards = document.querySelectorAll("div[data-show-author]");
                if (cards.length > 0) return { cards: cards.length };

                // Procura botão/link do CF por texto (case-insensitive) em
                // qualquer elemento clicável visível.
                const candidates = Array.from(document.querySelectorAll(
                    "button, a, input[type='button'], input[type='submit'], [role='button']"
                ));
                const needle = "verify you are human";
                for (const el of candidates) {
                    const text = (el.textContent || el.value || "").trim().toLowerCase();
                    if (!text.includes(needle)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    return {
                        btn: true,
                        tag: el.tagName,
                        x: r.left, y: r.top, w: r.width, h: r.height,
                    };
                }

                return {
                    nothing: true,
                    title: document.title,
                    url: location.href.slice(0, 120),
                    btn_count: candidates.length,
                };
            })())
            """
        )
        try:
            info = json.loads(raw) if isinstance(raw, str) else {}
        except (TypeError, ValueError):
            info = {}

        if info.get("cards"):
            logger.info(
                f"Challenge resolvido — {info['cards']} cards detectados "
                f"(tentativa {attempt})"
            )
            return True

        if info.get("btn"):
            click_x = info["x"] + info["w"] / 2
            click_y = info["y"] + info["h"] / 2
            logger.info(
                f"Challenge tentativa {attempt}/{max_retries}: clicando botão "
                f"{info['tag']} em ({click_x:.0f},{click_y:.0f})"
            )
            try:
                # Mouse move antes do click pra parecer gesto humano
                await tab.mouse_move(click_x, click_y)
                await tab.sleep(0.3)
                await tab.mouse_click(click_x, click_y)
            except Exception as e:
                logger.warning(f"mouse_click falhou: {e}")
        else:
            if attempt <= 5 or attempt % 5 == 0:
                logger.info(
                    f"Tentativa {attempt}: aguardando — title='{info.get('title', '?')}' "
                    f"url='{info.get('url', '?')}' botões={info.get('btn_count', '?')}"
                )

    logger.error(f"Challenge não bypassado após {max_retries} tentativas")
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

    # Bypass do challenge do CF — procura botão "Verify you are human" e clica
    bypassed = await _bypass_cloudflare_challenge(tab)
    if not bypassed:
        await tab.save_screenshot("/tmp/pelando_cf_failed.png")
        logger.error("Cloudflare challenge não bypassado. Screenshot: /tmp/pelando_cf_failed.png")
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
