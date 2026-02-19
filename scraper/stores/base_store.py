from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from models.pelando_deal import PelandoDeal
    from models.product import Product


class BaseStore(ABC):
    name: str
    display_name: str
    domain_url: str  # URL base do domínio (para carregar cookies)
    login_url: str  # URL para login manual

    @abstractmethod
    def process_deal(self, driver: "WebDriver", deal: "PelandoDeal") -> "Product | None":
        """
        Processa um deal do Pelando e retorna um Product com link de afiliado.
        Retorna None se falhar.
        """
        pass

    @abstractmethod
    def is_logged_in(self, driver: "WebDriver") -> bool:
        """Verifica se está logado no programa de afiliados da loja."""
        pass

    @abstractmethod
    def login(self, driver: "WebDriver") -> bool:
        """Realiza login no programa de afiliados. Retorna True se sucesso."""
        pass
