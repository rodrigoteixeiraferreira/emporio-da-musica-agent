"""Load the store's CSV tables into an in-memory SQLite database.

Data treatment done here (documented in the README, "Data treatment"):

* explicit types (ints, money as REAL, ISO dates as TEXT, empty strings -> NULL);
* ``specs`` parsed as JSON; for guitars/basses the numeric ``strings`` key is renamed
  ``string_count`` so it is not confused with the string *material* (nylon/steel) used
  for acoustic instruments;
* each product gets a ``brand`` and a search index (name, brand, category, specs,
  a few Portuguese synonyms);
* descriptions that name a *different* brand from the product (e.g. "Music Man Bass 1X"
  described as a Fender Jazz Bass) are flagged unreliable and hidden from the agent;
* customer e-mails are lower-cased and phones reduced to digits, for verification.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from .config import RAW_DIR

RAW_FILE = "desafio_tecnico_ai_eng - {}.csv"

KNOWN_BRANDS = [
    "Music Man", "Yamaha", "Tagima", "Giannini", "Rozini", "Shelby", "Crafter", "Martin",
    "Taylor", "Takamine", "Kala", "Ohana", "Kalani", "Fender", "Gibson", "Ibanez", "PRS",
    "Pearl", "Tama", "Korg", "Nord", "Roland",
]

STOPWORDS = {
    "a", "o", "as", "os", "e", "de", "do", "da", "dos", "das", "com", "para", "pra", "um",
    "uma", "uns", "umas", "no", "na", "em", "por", "que", "qual", "quais", "tem", "voces",
    "ai", "me", "meu", "minha", "the",
}

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    price_brl REAL NOT NULL,
    description TEXT,               -- NULL when the original text is unreliable
    description_raw TEXT,
    description_reliable INTEGER NOT NULL,
    stock_quantity INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    specs TEXT NOT NULL,            -- JSON object
    created_at TEXT,
    search_tokens TEXT NOT NULL     -- space-separated normalized tokens
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    first_name TEXT NOT NULL,
    phone TEXT,
    phone_digits TEXT,
    email TEXT,
    email_norm TEXT,
    city TEXT
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_brl REAL NOT NULL,
    payment_method TEXT,
    tracking_code TEXT,
    estimated_delivery TEXT,
    notes TEXT
);
CREATE TABLE order_items (
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL
);
CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent REAL NOT NULL,
    description TEXT,
    is_active INTEGER NOT NULL
);
"""


# --------------------------------------------------------------------------- text helpers

def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _stem(token: str) -> str:
    """Tiny Portuguese plural folding: violões -> violao, guitarras -> guitarra."""
    if len(token) > 4 and token.endswith(("oes", "aes")):
        return token[:-3] + "ao"
    if len(token) > 3 and token.endswith("s") and not token.isdigit():
        return token[:-1]
    return token


def tokenize(text: str, drop_stopwords: bool = False) -> list[str]:
    """Lower-case, strip accents, split on punctuation and on letter/digit boundaries.

    "Takamine GD-20" and "takamine gd20" both become ["takamine", "gd", "20"].
    """
    words = re.findall(r"[a-z0-9]+", strip_accents(text or "").lower())
    if drop_stopwords:
        # Filter whole words only, so the "e" in "D-28E" survives the split below.
        words = [w for w in words if w not in STOPWORDS]
    out = []
    for word in words:
        out += [_stem(p) for p in re.findall(r"[a-z]+|\d+", word)]
    return out


def phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 12 and digits.startswith("55"):
        digits = digits[2:]
    return digits


def find_brands(text: str) -> list[str]:
    found = []
    for brand in KNOWN_BRANDS:
        match = re.search(rf"\b{re.escape(brand)}\b", text or "", flags=re.IGNORECASE)
        if match:
            found.append((match.start(), brand))
    return [b for _, b in sorted(found)]


# --------------------------------------------------------------------------- loading

def _read_csv(raw_dir: Path, table: str) -> list[dict[str, str]]:
    with open(raw_dir / RAW_FILE.format(table), encoding="utf-8", newline="") as fh:
        return [{k: (v.strip() if v is not None else "") for k, v in row.items()} for row in csv.DictReader(fh)]


def _none_if_empty(value: str) -> str | None:
    return value if value != "" else None


def _normalize_specs(specs: dict, category_id: int) -> dict:
    specs = {str(k).strip(): (str(v).strip() if v is not None else v) for k, v in specs.items()}
    strings = specs.get("strings")
    if strings is not None and strings.isdigit():
        specs["string_count"] = specs.pop("strings")
    return specs


def _search_tokens(name: str, brand: str | None, category: str, description: str | None, specs: dict) -> str:
    words = [name, brand or "", category, description or ""]
    words += [str(v) for v in specs.values()]
    if specs.get("electronics") == "yes":
        words.append("eletroacustico eletrico captacao")
    if specs.get("strings") == "steel":
        words.append("aco")
    if specs.get("strings") == "nylon":
        words.append("classico")
    return " ".join(sorted(set(tokenize(" ".join(words), drop_stopwords=True))))


class StoreDB:
    """The store's operational data, loaded once per process into SQLite (in memory)."""

    def __init__(self, raw_dir: Path = RAW_DIR):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._load(raw_dir)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def _load(self, raw_dir: Path) -> None:
        cur = self.conn.cursor()

        categories = {}
        for r in _read_csv(raw_dir, "categories"):
            categories[int(r["category_id"])] = r["name"]
            cur.execute("INSERT INTO categories VALUES (?, ?, ?)",
                        (int(r["category_id"]), r["name"], _none_if_empty(r["description"])))

        for r in _read_csv(raw_dir, "products"):
            category_id = int(r["category_id"])
            specs = _normalize_specs(json.loads(r["specs"]), category_id)
            name_brands = find_brands(r["name"])
            brand = name_brands[0] if name_brands else None
            desc_brands = set(find_brands(r["description"]))
            reliable = not desc_brands or desc_brands == {brand}
            description = r["description"] if reliable else None
            cur.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    int(r["product_id"]), r["name"], brand, category_id, float(r["price_brl"]),
                    description, r["description"], int(reliable), int(r["stock_quantity"]),
                    r["status"], json.dumps(specs, ensure_ascii=False), _none_if_empty(r["created_at"]),
                    _search_tokens(r["name"], brand, categories[category_id], description, specs),
                ),
            )

        for r in _read_csv(raw_dir, "customers"):
            cur.execute(
                "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)",
                (
                    int(r["customer_id"]), r["name"], r["name"].split()[0], r["phone"],
                    phone_digits(r["phone"]), r["email"], r["email"].strip().lower(), r["city"],
                ),
            )

        for r in _read_csv(raw_dir, "orders"):
            cur.execute(
                "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    int(r["order_id"]), int(r["customer_id"]), r["order_date"], r["status"],
                    float(r["total_brl"]), _none_if_empty(r["payment_method"]),
                    _none_if_empty(r["tracking_code"]), _none_if_empty(r["estimated_delivery"]),
                    _none_if_empty(r["notes"]),
                ),
            )

        for r in _read_csv(raw_dir, "order_items"):
            cur.execute("INSERT INTO order_items VALUES (?,?,?)",
                        (int(r["order_id"]), int(r["product_id"]), int(r["quantity"])))

        for r in _read_csv(raw_dir, "promotions"):
            cur.execute(
                "INSERT INTO promotions VALUES (?,?,?,?,?)",
                (
                    int(r["promotion_id"]), int(r["product_id"]), float(r["discount_percent"]),
                    _none_if_empty(r["description"]), int(r["is_active"]),
                ),
            )
        self.conn.commit()
