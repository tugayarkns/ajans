"""Kanallar arasi stok senkronizasyonu icin yerel SQLite veritabani.

Shopify ve eBay birbirinden bagimsiz stok tutar; bu modul her SKU icin
"gercek/ortak" stok havuzunu (pool_qty) tek bir yerde saklar, boylece
main.py'deki sync_inventory() adimi hangi kanalda satis oldugunu tespit
edip diger kanala guncel miktari geri yazabilir.
"""
import sqlite3
from contextlib import closing
from datetime import datetime

DB_FILE = "inventory.db"


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                sku TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                pool_qty INTEGER NOT NULL,
                shopify_qty INTEGER,
                ebay_qty INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )


def upsert(sku, title, pool_qty, shopify_qty=None, ebay_qty=None):
    """Bir SKU'yu ekler/gunceller. Var olan alanlar verilmezse korunur."""
    with closing(_connect()) as conn, conn:
        existing = conn.execute("SELECT * FROM inventory WHERE sku = ?", (sku,)).fetchone()
        if existing:
            shopify_qty = existing["shopify_qty"] if shopify_qty is None else shopify_qty
            ebay_qty = existing["ebay_qty"] if ebay_qty is None else ebay_qty
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO inventory (sku, title, pool_qty, shopify_qty, ebay_qty, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                title = excluded.title,
                pool_qty = excluded.pool_qty,
                shopify_qty = excluded.shopify_qty,
                ebay_qty = excluded.ebay_qty,
                updated_at = excluded.updated_at
            """,
            (sku, title, pool_qty, shopify_qty, ebay_qty, now),
        )


def get(sku):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM inventory WHERE sku = ?", (sku,)).fetchone()
        return dict(row) if row else None


def get_all():
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM inventory ORDER BY sku").fetchall()
        return [dict(r) for r in rows]
