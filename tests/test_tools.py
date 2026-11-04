"""Tool behaviour, without calling the model API. Reference date: Wed 25/03/2026 10:00."""

import json
from datetime import datetime

import pytest

from emporio_agent.config import STORE_TZ
from emporio_agent.tools import TOOL_DECLARATIONS, TOOL_NAMES, StoreTools

NOW = datetime(2026, 3, 25, 10, 0, tzinfo=STORE_TZ)


@pytest.fixture
def tools(db, tmp_path):
    return StoreTools(db, now=lambda: NOW, handoffs_file=tmp_path / "handoffs.jsonl")


def ids(products):
    return {p["product_id"] for p in products}


# ------------------------------------------------------------------ search

def test_search_by_category_and_max_price_excludes_unavailable(tools):
    r = tools.search_products(category="Violões", max_price=1000)
    assert ids(r["products"]) == {81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 107, 112}
    assert all(p["category"] == "Violões" for p in r["products"])
    assert ids(r["matching_but_unavailable"]) == {96, 113}  # out of stock, discontinued
    prices = [float(p["price"].replace("R$ ", "").replace(".", "").replace(",", ".")) for p in r["products"]]
    assert prices == sorted(prices) and max(prices) <= 1000


def test_search_can_include_unavailable(tools):
    r = tools.search_products(category="Violões", max_price=1000, include_unavailable=True)
    assert {96, 113} <= ids(r["products"])


def test_search_excludes_coming_soon_by_default(tools):
    r = tools.search_products(category="Ukuleles")
    assert 130 not in ids(r["products"])
    assert 130 in ids(r["matching_but_unavailable"])


def test_search_by_feature_uses_specs(tools):
    r = tools.search_products(query="com captação", category="Violões", max_price=1500)
    assert ids(r["products"]) == {99, 101, 103, 107}


def test_search_filters_on_promotional_price(tools):
    # Crafter HT-100 lists at R$ 2.399,00 but costs R$ 1.967,18 with its active 18% promotion.
    r = tools.search_products(category="Violões", min_price=1890, max_price=2000)
    assert ids(r["products"]) == {90, 104}


def test_category_names_are_matched_exactly_first(tools):
    r = tools.search_products(category="Instrumentos de Sopro (Metais)")
    assert r["filters"]["category"] == "Instrumentos de Sopro (Metais)" and r["total_found"] == 0


# ------------------------------------------------------------------ product detail and prices

def test_active_promotion_is_applied_and_pix_is_not_stacked(tools):
    p = tools.get_product("90")
    assert p["pricing"]["list_price"] == "R$ 2.399,00"
    assert p["pricing"]["active_promotion"]["discount_percent"] == 18
    assert p["pricing"]["final_price"] == "R$ 1.967,18"
    assert p["pricing"]["pix"]["price"] is None


def test_inactive_promotion_is_ignored_and_pix_applies(tools):
    p = tools.get_product("Takamine GD20")
    assert p["match"] == "exact" and p["product_id"] == 95
    assert p["pricing"]["active_promotion"] is None
    assert p["pricing"]["final_price"] == "R$ 2.199,00"
    assert p["pricing"]["pix"]["price"] == "R$ 2.089,05"
    assert "10x de R$ 219,90" in p["pricing"]["credit_card"]["options"]
    assert p["pricing"]["credit_card"]["max_installments"] == 12
    assert p["expired_promotions"] == [{"name": "Oferta Especial", "discount_percent": 12, "status": "encerrada"}]


@pytest.mark.parametrize("name", ["takamine gd-20", "Takamine GD 20", "TAKAMINE GD20"])
def test_name_variants_resolve_to_the_same_product(tools, name):
    assert tools.get_product(name)["product_id"] == 95


def test_ambiguous_name_returns_candidates(tools):
    r = tools.get_product("Martin D-28")
    assert r["match"] == "ambiguous" and ids(r["candidates"]) == {93, 108}
    r = tools.get_product("Taylor")
    assert r["match"] == "ambiguous" and ids(r["candidates"]) == {94, 106}


def test_similar_name_is_never_confirmed(tools):
    r = tools.get_product("Takamine G20")
    assert r["match"] == "none"
    assert 95 in ids(r["candidates"])
    assert "product_id" not in r


def test_unavailable_product_brings_available_alternatives(tools):
    p = tools.get_product("Giannini GF-3D Dreadnought Sunburst")
    assert p["product_id"] == 96 and p["stock_quantity"] == 0
    assert len(p["alternatives"]) == 3
    assert all(a["availability"] == "disponível" and a["category"] == "Violões" for a in p["alternatives"])
    # Same brand and finish first, then the closest prices; model-code fragments ("3", "d") do not count.
    assert [a["product_id"] for a in p["alternatives"]] == [88, 107, 91]
    discontinued = tools.get_product("113")
    assert "descontinuado" in discontinued["availability"]
    assert {109, 110} <= ids(discontinued["alternatives"])  # other 7-string nylon guitars


def test_unreliable_description_is_not_exposed(tools):
    p = tools.get_product("135")
    assert p["description"] is None and "description_note" in p


def test_active_promotions_list(tools):
    r = tools.list_active_promotions()
    assert ids(r["active_promotions"]) == {127, 121, 90, 94}
    assert ids(tools.list_active_promotions(category="Ukuleles")["active_promotions"]) == {127, 121}


# ------------------------------------------------------------------ quotes and shipping

def test_metro_shipping_below_and_above_500(tools):
    one = tools.quote_order([{"product_id": 83, "quantity": 1}], city="Campo Grande")
    assert one["shipping"]["fee"] == "R$ 35,00" and one["total"] == "R$ 464,90"
    two = tools.quote_order([{"product_id": 83, "quantity": 2}], city="Campo Grande")
    assert two["shipping"]["fee"] == "R$ 0,00" and two["total"] == "R$ 859,80"


def test_other_cities_are_not_quoted(tools):
    r = tools.quote_order([{"product_id": 95, "quantity": 1}], city="Dourados")
    assert r["shipping"]["fee"] is None and r["total"] is None


def test_quote_pix_only_on_items_without_promotion(tools):
    r = tools.quote_order([{"product_id": 90, "quantity": 1}, {"product_id": 95, "quantity": 1}], city="Campo Grande")
    # 1967.18 (promo, no PIX) + 2089.05 (2199 - 5%) + free shipping
    assert r["pix_total"] == "R$ 4.056,23"
    assert r["combined_payment_allowed"] is True


def test_quote_warns_about_stock(tools):
    r = tools.quote_order([{"product_id": 93, "quantity": 3}], city="Campo Grande")
    assert any("só há 2" in w for w in r["warnings"])


# ------------------------------------------------------------------ orders

def test_order_status_requires_matching_contact(tools):
    ok = tools.get_order_status(8, "anacarol.ferreira@coldmail.com")
    assert ok["verified"] and ok["status"] == "shipped" and ok["tracking_code"] == "BRJL5544332BR"
    by_phone = tools.get_order_status(8, "(67) 99654-7821")
    assert by_phone["verified"]
    wrong = tools.get_order_status(8, "lucas.mendes@jmail.com")  # another customer's e-mail
    assert wrong["verified"] is False
    assert "status" not in wrong and "items" not in wrong and "tracking_code" not in wrong


def test_unknown_order_and_wrong_contact_look_the_same(tools):
    a = tools.get_order_status(999, "anacarol.ferreira@coldmail.com")
    b = tools.get_order_status(8, "someone@else.com")
    assert a["error"] == b["error"]


def test_verification_locks_after_three_failures(tools):
    for _ in range(3):
        tools.get_order_status(8, "x@y.com")
    locked = tools.get_order_status(8, "anacarol.ferreira@coldmail.com")
    assert locked["verified"] is False and "bloqueada" in locked["error"]


def test_late_shipment_is_flagged(tools):
    r = tools.get_order_status(8, "67996547821")
    assert r["is_late"] is True and r["days_late"] == 25


def test_cancelled_order_shows_reason(tools):
    r = tools.get_order_status(19, "pedro.oliveira@jmail.com")
    assert r["status"] == "cancelled" and "Pagamento não confirmado" in r["cancellation_reason"]


# ------------------------------------------------------------------ returns

LETICIA = "leticia.rocha@jmail.com"  # order 7: bought 03/02/2026, delivered 17/02/2026


def test_regret_outside_window_offers_alternatives(tools):
    r = tools.check_return_eligibility(7, LETICIA, "arrependimento")
    assert r["eligible"] is False
    assert r["deadline"] == "24/02/2026" and r["days_elapsed"] == 36
    assert any("18/05/2026" in a for a in r["alternatives"])  # legal warranty until receipt + 90 days


def test_defect_window_counts_from_purchase_date(tools):
    r = tools.check_return_eligibility(7, LETICIA, "defeito")
    assert r["eligible"] is False and r["deadline"] == "05/03/2026"


def test_preference_window(tools):
    r = tools.check_return_eligibility(7, LETICIA, "preferência")
    assert r["eligible"] is False and r["deadline"] == "24/02/2026"


def test_regret_inside_window(db, tmp_path):
    early = StoreTools(db, now=lambda: datetime(2026, 2, 20, 10, 0, tzinfo=STORE_TZ), handoffs_file=tmp_path / "h.jsonl")
    r = early.check_return_eligibility(7, LETICIA, "arrependimento")
    assert r["eligible"] is True and r["days_left"] == 4
    assert "alternatives" not in r


def test_return_requires_verification(tools):
    r = tools.check_return_eligibility(7, "lucas.mendes@jmail.com", "arrependimento")
    assert r["verified"] is False and "eligible" not in r


def test_not_shipped_order_goes_to_humans(tools):
    r = tools.check_return_eligibility(13, "fernanda.ribeiro@coldmail.com", "arrependimento")
    assert r["eligible"] is None and "escalate_to_human" in r["next_step"]


# ------------------------------------------------------------------ store and handoff

def test_store_status(tools):
    r = tools.get_store_status()
    assert r["is_open"] is True and r["closes_at"] == "18:00"
    assert r["now"].startswith("quarta-feira, 25/03/2026 10:00")


def test_escalation_writes_jsonl_and_returns_protocol(tools):
    first = tools.escalate_to_human("Cliente reclama de atraso", reason="reclamacao", customer_contact="x@y.com")
    second = tools.escalate_to_human("Cotação de frete para Dourados", reason="outro")
    assert first["protocol"] == "EM-20260325-0001" and second["protocol"] == "EM-20260325-0002"
    assert first["return_deadline"] == "até 24 horas úteis"
    lines = tools.handoffs_file.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["summary"] == "Cliente reclama de atraso"


# ------------------------------------------------------------------ dispatch

def test_dispatch_and_declarations(tools):
    assert TOOL_NAMES == {d["name"] for d in TOOL_DECLARATIONS}
    assert all(hasattr(tools, name) for name in TOOL_NAMES)
    assert tools.call("get_product", {"product": "95"})["product_id"] == 95
    assert "error" in tools.call("drop_tables", {})
    assert "error" in tools.call("get_product", {"wrong": 1})
