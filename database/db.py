import sqlite3
import logging
from models.product import Product
import config

logger = logging.getLogger("DB")


def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            mlb_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            price TEXT,
            original_price TEXT,
            coupon TEXT,
            image_url TEXT,
            affiliate_link TEXT,
            badge TEXT,
            earnings_pct TEXT,
            rating TEXT,
            sales_info TEXT,
            created_at TEXT
        )
    """)
    # Migrações - adicionar colunas se não existirem
    for col in ["original_price", "coupon"]:
        try:
            conn.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT")
            logger.info(f"Coluna {col} adicionada à tabela products")
        except sqlite3.OperationalError:
            pass  # Coluna já existe
    # Tabela para rastrear deals já processados (evita reprocessar)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_deals (
            deal_url TEXT PRIMARY KEY,
            processed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Banco de dados inicializado")


def is_deal_processed(deal_url: str) -> bool:
    """Verifica se um deal já foi processado (pela URL do Pelando)."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.execute("SELECT 1 FROM processed_deals WHERE deal_url = ?", (deal_url,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def mark_deal_processed(deal_url: str):
    """Marca um deal como processado."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO processed_deals (deal_url) VALUES (?)",
        (deal_url,),
    )
    conn.commit()
    conn.close()


def should_process(mlb_id: str, current_price: str) -> bool:
    """Retorna True se o produto é novo OU se o preço mudou."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.execute("SELECT price FROM products WHERE mlb_id = ?", (mlb_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return True

    saved_price = row[0]
    if saved_price != current_price:
        logger.info(f"Produto {mlb_id} mudou de preço: {saved_price} -> {current_price}, será re-divulgado")
        return True

    return False


def save_product(product: Product):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO products (mlb_id, title, price, original_price, coupon, image_url, affiliate_link, badge, earnings_pct, rating, sales_info, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                product.mlb_id,
                product.title,
                product.price,
                product.original_price,
                product.coupon,
                product.image_url,
                product.affiliate_link,
                product.badge,
                product.earnings_pct,
                product.rating,
                product.sales_info,
                product.created_at,
            ),
        )
        conn.commit()
        logger.info(f"Produto {product.mlb_id} salvo: {product.title[:50]}")
    finally:
        conn.close()


def cleanup_old_products(days: int = 7):
    """Remove produtos com mais de N dias do banco."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.execute(
        "DELETE FROM products WHERE created_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        logger.info(f"Limpeza: {deleted} produtos com mais de {days} dias removidos")


def cleanup_old_deals(days: int = 1):
    """Remove deals processados com mais de N dias."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.execute(
        "DELETE FROM processed_deals WHERE processed_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        logger.info(f"Limpeza: {deleted} deals antigos removidos")
