from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import nodriver
    from models.pelando_deal import PelandoDeal
    from models.product import Product


class BaseStore(ABC):
    name: str
    display_name: str
    domain_url: str
    login_url: str

    @abstractmethod
    async def process_deal(self, tab: "nodriver.Tab", deal: "PelandoDeal") -> "Product | None":
        """
        Processa um deal do Pelando e retorna um Product com link de afiliado.
        Retorna None se falhar.
        """
        pass

    @abstractmethod
    async def is_logged_in(self, browser: "nodriver.Browser") -> bool:
        """Verifica se está logado no programa de afiliados da loja."""
        pass

    @abstractmethod
    async def login(self, browser: "nodriver.Browser") -> bool:
        """Realiza login no programa de afiliados. Retorna True se sucesso."""
        pass
