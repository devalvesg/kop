from dataclasses import dataclass


@dataclass
class PelandoDeal:
    title: str
    price: str
    image_url: str
    temperature: str
    store_name: str
    deal_url: str
    store_link_url: str = ""
