from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Product:
    mlb_id: str
    title: str
    price: str
    image_url: str
    affiliate_link: str = ""
    original_price: str = ""  # Preço original (antes do desconto)
    coupon: str = ""  # Cupom disponível (ex: "R$5 OFF", "10% OFF")
    badge: str = ""
    earnings_pct: str = ""
    rating: str = ""
    sales_info: str = ""
    temperature: str = ""
    source: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
