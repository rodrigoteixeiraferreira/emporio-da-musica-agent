"""The loaded data matches what we mapped from the raw CSVs and the manual."""

import json

from emporio_agent.config import POLICIES_MD, POLICIES_PDF
from emporio_agent.db import tokenize
from emporio_agent.policies import pdf_to_markdown


def _count(db, table):
    return db.one(f"SELECT COUNT(*) FROM {table}")[0]


def test_row_counts(db):
    assert _count(db, "products") == 65
    assert _count(db, "customers") == 50
    assert _count(db, "orders") == 20
    assert _count(db, "order_items") == 22
    assert _count(db, "promotions") == 25
    assert _count(db, "categories") == 9


def test_product_status_and_stock(db):
    status = dict(db.query("SELECT status, COUNT(*) FROM products GROUP BY status"))
    assert status == {"active": 62, "discontinued": 2, "coming_soon": 1}
    out_of_stock = {r[0] for r in db.query("SELECT product_id FROM products WHERE stock_quantity = 0")}
    assert out_of_stock == {96, 113}


def test_order_status_and_tracking(db):
    status = dict(db.query("SELECT status, COUNT(*) FROM orders GROUP BY status"))
    assert status == {"delivered": 7, "confirmed": 4, "pending": 4, "cancelled": 4, "shipped": 1}
    with_tracking = db.query("SELECT DISTINCT status FROM orders WHERE tracking_code IS NOT NULL")
    assert {r[0] for r in with_tracking} == {"delivered", "shipped"}
    with_eta = db.query("SELECT DISTINCT status FROM orders WHERE estimated_delivery IS NOT NULL")
    assert {r[0] for r in with_eta} == {"delivered", "shipped"}
    cancelled_without_reason = db.one("SELECT COUNT(*) FROM orders WHERE status='cancelled' AND notes IS NULL")[0]
    assert cancelled_without_reason == 0


def test_only_four_promotions_are_active(db):
    active = {r[0] for r in db.query("SELECT product_id FROM promotions WHERE is_active = 1")}
    assert active == {127, 121, 90, 94}


def test_specs_are_json_and_string_count_is_disambiguated(db):
    for (specs,) in db.query("SELECT specs FROM products"):
        assert isinstance(json.loads(specs), dict)
    guitar = json.loads(db.one("SELECT specs FROM products WHERE product_id = 145")[0])
    assert guitar["string_count"] == "6" and "strings" not in guitar
    violao = json.loads(db.one("SELECT specs FROM products WHERE product_id = 81")[0])
    assert violao["strings"] == "nylon"


def test_descriptions_naming_another_brand_are_hidden(db):
    row = db.one("SELECT brand, description, description_reliable FROM products WHERE product_id = 135")
    assert row["brand"] == "Music Man"
    assert row["description"] is None and row["description_reliable"] == 0  # text talks about a Fender
    ok = db.one("SELECT description, description_reliable FROM products WHERE product_id = 95")
    assert ok["description_reliable"] == 1 and "Takamine" in ok["description"]


def test_tokenize_folds_accents_plurals_and_model_codes():
    assert tokenize("Violões") == tokenize("violao")
    assert tokenize("Takamine GD-20") == tokenize("takamine gd20") == ["takamine", "gd", "20"]
    assert tokenize("Martin D-28E", drop_stopwords=True) == ["martin", "d", "28", "e"]
    assert tokenize("quais violões com captação", drop_stopwords=True) == ["violao", "captacao"]


def test_policies_markdown_is_up_to_date_and_complete():
    committed = POLICIES_MD.read_text(encoding="utf-8")
    assert committed == pdf_to_markdown(POLICIES_PDF)
    for needle in ["### 3.1 Regras de Parcelamento", "### 4.1 Direito de Arrependimento",
                   "(67) 3321-4500", "24 horas úteis", "## 9. Privacidade"]:
        assert needle in committed
