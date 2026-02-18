from scraper.stores.base_store import BaseStore
from scraper.stores.mercadolivre import MercadoLivreStore
from scraper.stores.amazon import AmazonStore

STORE_HANDLERS: dict[str, BaseStore] = {
    "Mercado Livre": MercadoLivreStore(),
    "Amazon": AmazonStore(),
}


def get_handler(store_name: str) -> BaseStore | None:
    """Retorna o handler para a loja especificada."""
    return STORE_HANDLERS.get(store_name)


def get_supported_stores() -> set[str]:
    """Retorna set de lojas suportadas."""
    return set(STORE_HANDLERS.keys())
