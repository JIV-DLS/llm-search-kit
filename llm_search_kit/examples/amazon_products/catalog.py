"""Amazon-products demo catalog.

A self-contained in-memory SQLite catalog seeded with ~25 sample products
so the demo runs with zero external setup. Replace this class with your
real DB / REST adapter -- the only contract is
``async def search(filters, query, sort_by, skip, limit) -> {items, total}``.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from llm_search_kit.search import CatalogBackend


SEED_PRODUCTS: List[Dict[str, Any]] = [
    {"id": "p1", "title": "Nike Air Zoom Pegasus 40 Running Shoes", "category": "shoes", "brand": "Nike", "color": "red", "size": "42", "price": 119.0, "rating": 4.6, "prime": True},
    {"id": "p2", "title": "Nike Revolution 6 Sneakers", "category": "shoes", "brand": "Nike", "color": "black", "size": "42", "price": 65.0, "rating": 4.4, "prime": True},
    {"id": "p3", "title": "Adidas Ultraboost 22", "category": "shoes", "brand": "Adidas", "color": "white", "size": "43", "price": 180.0, "rating": 4.7, "prime": True},
    {"id": "p4", "title": "Puma Roma Classic Sneakers", "category": "shoes", "brand": "Puma", "color": "white", "size": "41", "price": 55.0, "rating": 4.2, "prime": False},
    {"id": "p5", "title": "Converse Chuck Taylor All Star", "category": "shoes", "brand": "Converse", "color": "red", "size": "42", "price": 49.0, "rating": 4.5, "prime": True},
    {"id": "p6", "title": "Apple iPhone 15 128GB", "category": "phones", "brand": "Apple", "color": "black", "size": None, "price": 799.0, "rating": 4.8, "prime": True},
    {"id": "p7", "title": "Samsung Galaxy S24 256GB", "category": "phones", "brand": "Samsung", "color": "grey", "size": None, "price": 749.0, "rating": 4.6, "prime": True},
    {"id": "p8", "title": "Google Pixel 8a", "category": "phones", "brand": "Google", "color": "blue", "size": None, "price": 499.0, "rating": 4.5, "prime": True},
    {"id": "p9", "title": "OnePlus 12R", "category": "phones", "brand": "OnePlus", "color": "blue", "size": None, "price": 599.0, "rating": 4.4, "prime": False},
    {"id": "p10", "title": "MacBook Air M3 13\"", "category": "laptops", "brand": "Apple", "color": "grey", "size": "13 inch", "price": 1099.0, "rating": 4.8, "prime": True},
    {"id": "p11", "title": "Dell XPS 13", "category": "laptops", "brand": "Dell", "color": "black", "size": "13 inch", "price": 999.0, "rating": 4.5, "prime": True},
    {"id": "p12", "title": "Lenovo ThinkPad X1 Carbon", "category": "laptops", "brand": "Lenovo", "color": "black", "size": "14 inch", "price": 1399.0, "rating": 4.6, "prime": False},
    {"id": "p13", "title": "Sony WH-1000XM5 Headphones", "category": "headphones", "brand": "Sony", "color": "black", "size": None, "price": 349.0, "rating": 4.7, "prime": True},
    {"id": "p14", "title": "Bose QuietComfort Ultra", "category": "headphones", "brand": "Bose", "color": "white", "size": None, "price": 429.0, "rating": 4.6, "prime": True},
    {"id": "p15", "title": "JBL Tune 760NC", "category": "headphones", "brand": "JBL", "color": "black", "size": None, "price": 99.0, "rating": 4.3, "prime": True},
    {"id": "p16", "title": "Apple Watch Series 9", "category": "watches", "brand": "Apple", "color": "pink", "size": "41mm", "price": 399.0, "rating": 4.7, "prime": True},
    {"id": "p17", "title": "Garmin Forerunner 265", "category": "watches", "brand": "Garmin", "color": "black", "size": "46mm", "price": 449.0, "rating": 4.6, "prime": True},
    {"id": "p18", "title": "Casio G-Shock GA-2100", "category": "watches", "brand": "Casio", "color": "black", "size": "45mm", "price": 99.0, "rating": 4.5, "prime": False},
    {"id": "p19", "title": "Levi's 501 Original Fit Jeans", "category": "shirts", "brand": "Levi's", "color": "blue", "size": "M", "price": 59.0, "rating": 4.4, "prime": True},
    {"id": "p20", "title": "Uniqlo Supima Cotton T-Shirt", "category": "shirts", "brand": "Uniqlo", "color": "white", "size": "M", "price": 19.0, "rating": 4.3, "prime": False},
    {"id": "p21", "title": "Hanes ComfortSoft T-Shirt 5-pack", "category": "shirts", "brand": "Hanes", "color": "black", "size": "L", "price": 24.0, "rating": 4.5, "prime": True},
    {"id": "p22", "title": "The Pragmatic Programmer (book)", "category": "books", "brand": "Addison-Wesley", "color": None, "size": None, "price": 35.0, "rating": 4.8, "prime": True},
    {"id": "p23", "title": "Designing Data-Intensive Applications", "category": "books", "brand": "O'Reilly", "color": None, "size": None, "price": 45.0, "rating": 4.9, "prime": True},
    {"id": "p24", "title": "Instant Pot Duo 7-in-1 6Qt", "category": "kitchen", "brand": "Instant Pot", "color": "grey", "size": "6Qt", "price": 89.0, "rating": 4.7, "prime": True},
    {"id": "p25", "title": "Ninja Foodi Air Fryer", "category": "kitchen", "brand": "Ninja", "color": "black", "size": "5.5Qt", "price": 129.0, "rating": 4.6, "prime": True},
]


class InMemoryAmazonCatalog(CatalogBackend):
    """SQLite-backed (in-memory) catalog seeded with sample products."""

    def __init__(self, products: Optional[List[Dict[str, Any]]] = None) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._setup(products or SEED_PRODUCTS)

    def _setup(self, products: List[Dict[str, Any]]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE products (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT,
                color TEXT,
                size TEXT,
                price REAL NOT NULL,
                rating REAL NOT NULL,
                prime INTEGER NOT NULL
            )
            """
        )
        for p in products:
            cur.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p["id"],
                    p["title"],
                    p["category"],
                    p.get("brand"),
                    p.get("color"),
                    p.get("size"),
                    float(p["price"]),
                    float(p["rating"]),
                    1 if p.get("prime") else 0,
                ),
            )
        self._conn.commit()

    async def search(
        self,
        filters: Dict[str, Any],
        query: str = "",
        sort_by: str = "relevance",
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        where: List[str] = []
        params: List[Any] = []

        if filters.get("category"):
            where.append("category = ?")
            params.append(filters["category"])
        if filters.get("brand"):
            where.append("LOWER(brand) = LOWER(?)")
            params.append(filters["brand"])
        if filters.get("color"):
            where.append("LOWER(color) = LOWER(?)")
            params.append(filters["color"])
        if filters.get("size"):
            where.append("LOWER(size) = LOWER(?)")
            params.append(filters["size"])
        if filters.get("min_price") is not None:
            where.append("price >= ?")
            params.append(float(filters["min_price"]))
        if filters.get("max_price") is not None:
            where.append("price <= ?")
            params.append(float(filters["max_price"]))
        if filters.get("min_rating") is not None:
            where.append("rating >= ?")
            params.append(float(filters["min_rating"]))
        if filters.get("prime_only"):
            where.append("prime = 1")

        if query:
            tokens = [t for t in query.lower().split() if t]
            for tok in tokens:
                where.append("(LOWER(title) LIKE ? OR LOWER(brand) LIKE ?)")
                params.extend([f"%{tok}%", f"%{tok}%"])

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        order_sql = " ORDER BY rating DESC, price ASC"
        if sort_by == "price_asc":
            order_sql = " ORDER BY price ASC"
        elif sort_by == "price_desc":
            order_sql = " ORDER BY price DESC"
        elif sort_by == "newest":
            order_sql = " ORDER BY id DESC"
        elif sort_by == "rating_desc":
            order_sql = " ORDER BY rating DESC"

        cur = self._conn.cursor()
        count_sql = f"SELECT COUNT(*) AS c FROM products{where_sql}"
        total = int(cur.execute(count_sql, params).fetchone()["c"])

        rows = cur.execute(
            f"SELECT * FROM products{where_sql}{order_sql} LIMIT ? OFFSET ?",
            [*params, int(limit), int(skip)],
        ).fetchall()

        items = [
            {
                "id": r["id"],
                "title": r["title"],
                "category": r["category"],
                "brand": r["brand"],
                "color": r["color"],
                "size": r["size"],
                "price": r["price"],
                "rating": r["rating"],
                "prime": bool(r["prime"]),
            }
            for r in rows
        ]
        return {"items": items, "total": total}

    def close(self) -> None:
        self._conn.close()
