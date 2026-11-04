"""The tools exposed to the model.

Every number the agent tells a customer (price, discount, installment, shipping fee,
stock, order status, deadline) comes from here. Tools return plain JSON-serializable
dicts; money is pre-formatted as "R$ 1.234,56" so the model only has to read it.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from . import pricing, rules
from .config import HANDOFFS_FILE, STORE_EMAIL, STORE_PHONE, STORE_WHATSAPP, store_now
from .db import StoreDB, phone_digits, strip_accents, tokenize

AVAILABILITY_PT = {
    "in_stock": "disponível",
    "out_of_stock": "esgotado (temporariamente indisponível)",
    "discontinued": "descontinuado (não faz mais parte do catálogo)",
    "coming_soon": "em breve (ainda não disponível para compra)",
}
ORDER_STATUS_PT = {
    "pending": "pendente (aguardando confirmação do pagamento)",
    "confirmed": "confirmado (pagamento aprovado, em separação)",
    "shipped": "enviado (em transporte)",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
RETURN_REASONS = ["arrependimento", "defeito", "preferencia"]
ESCALATION_REASONS = ["reclamacao", "troca_devolucao", "pedido", "pergunta_sem_resposta", "outro"]
MAX_VERIFICATION_FAILURES = 3
MAX_SEARCH_RESULTS = 20


def _fmt_date(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _payment_label(method: str | None) -> str | None:
    if not method:
        return None
    if method.startswith("credit_"):
        return f"cartão de crédito em {method.split('_', 1)[1]}"
    return {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}.get(method, method)


class StoreTools:
    """Tool implementations bound to one database and one conversation session."""

    def __init__(
        self,
        db: StoreDB,
        now: Callable[[], datetime] = store_now,
        handoffs_file: Path = HANDOFFS_FILE,
    ):
        self.db = db
        self.now = now
        self.handoffs_file = handoffs_file
        self.verification_failures = 0
        self.categories = {r["category_id"]: r["name"] for r in db.query("SELECT * FROM categories")}

    # ------------------------------------------------------------------ dispatch

    def call(self, name: str, args: dict[str, Any] | None) -> dict:
        method = getattr(self, name, None)
        if name.startswith("_") or name not in TOOL_NAMES or method is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return method(**(args or {}))
        except TypeError as exc:  # bad or missing arguments from the model
            return {"error": f"invalid arguments for {name}: {exc}"}

    # ------------------------------------------------------------------ product helpers

    def _active_promotion(self, product_id: int):
        # Promotions do not stack (6.2); if several were active, the best one would apply.
        return self.db.one(
            "SELECT description, discount_percent FROM promotions "
            "WHERE product_id = ? AND is_active = 1 ORDER BY discount_percent DESC LIMIT 1",
            (product_id,),
        )

    @staticmethod
    def _availability(row) -> str:
        if row["status"] == "discontinued":
            return "discontinued"
        if row["status"] == "coming_soon":
            return "coming_soon"
        return "in_stock" if row["stock_quantity"] > 0 else "out_of_stock"

    def _final_price(self, row) -> tuple[Decimal, Any]:
        promo = self._active_promotion(row["product_id"])
        price = pricing.promotional_price(row["price_brl"], promo["discount_percent"] if promo else None)
        return price, promo

    def _summary(self, row) -> dict:
        final, promo = self._final_price(row)
        availability = self._availability(row)
        out = {
            "product_id": row["product_id"],
            "name": row["name"],
            "category": self.categories[row["category_id"]],
            "availability": AVAILABILITY_PT[availability],
            "stock_quantity": row["stock_quantity"],
            "price": pricing.fmt_brl(final),
        }
        if promo:
            out["promotion"] = {
                "name": promo["description"],
                "discount_percent": int(promo["discount_percent"]),
                "original_price": pricing.fmt_brl(row["price_brl"]),
            }
        pix = pricing.pix_price(row["price_brl"], promo is not None)
        out["pix_price"] = pricing.fmt_brl(pix) if pix is not None else None
        n = pricing.max_installments(final)
        out["max_installments"] = f"{n}x de {pricing.fmt_brl(pricing.installment_value(final, n))} sem juros"
        return out

    def _category_id(self, category: str) -> int | None:
        """Exact category name first; otherwise a unique first-word match ('violão' -> Violões)."""
        wanted = tokenize(category)
        for cid, name in self.categories.items():
            if tokenize(name) == wanted:
                return cid
        loose = [cid for cid, name in self.categories.items() if wanted[:1] == tokenize(name)[:1]]
        return loose[0] if len(loose) == 1 else None

    def _all_products(self):
        return self.db.query("SELECT * FROM products ORDER BY product_id")

    def _alternatives(self, row, limit: int = 3) -> list[dict]:
        """Similar products that can be bought now: same category, most shared name words, closest price.

        Only real words count (brand, body type, string type, finish): fragments of model codes such as
        the "3" and "d" of "GF-3D" would otherwise make unrelated models look similar.
        """
        def words(name: str) -> set[str]:
            return {t for t in tokenize(name) if t.isalpha() and len(t) >= 3} - {"natural"}

        own_words = words(row["name"])
        own_price, _ = self._final_price(row)
        candidates = []
        for other in self.db.query(
            "SELECT * FROM products WHERE category_id = ? AND product_id != ? "
            "AND status = 'active' AND stock_quantity > 0",
            (row["category_id"], row["product_id"]),
        ):
            shared = len(own_words & words(other["name"]))
            price, _ = self._final_price(other)
            candidates.append((-shared, abs(price - own_price), other))
        candidates.sort(key=lambda c: (c[0], c[1]))
        return [self._summary(c[2]) for c in candidates[:limit]]

    # ------------------------------------------------------------------ tools: catalog

    def search_products(
        self,
        query: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        include_unavailable: bool = False,
    ) -> dict:
        terms = tokenize(query or "", drop_stopwords=True)
        category_id = self._category_id(category) if category else None
        if category and category_id is None:
            return {"error": f"unknown category '{category}'", "categories": list(self.categories.values())}

        results, unavailable = [], []
        for row in self._all_products():
            if category_id and row["category_id"] != category_id:
                continue
            hay = row["search_tokens"].split()
            if terms and not all(any(h == t or (len(t) >= 3 and not t.isdigit() and h.startswith(t)) for h in hay)
                                 for t in terms):
                continue
            final, _ = self._final_price(row)
            if min_price is not None and final < pricing.money(min_price):
                continue
            if max_price is not None and final > pricing.money(max_price):
                continue
            if self._availability(row) != "in_stock" and not include_unavailable:
                unavailable.append({"product_id": row["product_id"], "name": row["name"],
                                    "availability": AVAILABILITY_PT[self._availability(row)]})
                continue
            results.append((final, row))

        results.sort(key=lambda r: r[0])
        out = {
            "filters": {"query": query, "category": self.categories.get(category_id), "min_price": min_price,
                        "max_price": max_price, "prices_compared": "preço final (com promoção ativa, se houver)"},
            "total_found": len(results),
            "products": [self._summary(r) for _, r in results[:MAX_SEARCH_RESULTS]],
        }
        if len(results) > MAX_SEARCH_RESULTS:
            out["note"] = f"Mostrando os {MAX_SEARCH_RESULTS} mais baratos; refine a busca para ver outros."
        if unavailable:
            out["matching_but_unavailable"] = unavailable
        if not results:
            out["note"] = "Nenhum produto disponível com esses filtros."
        return out

    def get_product(self, product: str) -> dict:
        text = str(product).strip()
        if text.isdigit():
            row = self.db.one("SELECT * FROM products WHERE product_id = ?", (int(text),))
            if row:
                return self._detail(row)

        query = tokenize(text, drop_stopwords=True)
        if not query:
            return {"match": "none", "message": "Informe o nome ou o código do produto."}

        exact, partial = [], []
        for row in self._all_products():
            name_tokens = tokenize(row["name"], drop_stopwords=True)
            if name_tokens == query:
                return self._detail(row)
            vocabulary = set(name_tokens) | set(tokenize(self.categories[row["category_id"]]))
            hits = sum(1 for t in query if t in vocabulary)
            if hits == len(query):
                exact.append(row)
            elif hits:
                partial.append((hits, row))

        if len(exact) == 1:
            return self._detail(exact[0])
        if exact:
            return {
                "match": "ambiguous",
                "message": "Mais de um produto corresponde ao nome. Pergunte ao cliente qual deles; não escolha por ele.",
                "candidates": [self._summary(r) for r in exact[:8]],
            }
        partial.sort(key=lambda p: -p[0])
        return {
            "match": "none",
            "message": ("Nenhum produto com esse nome exato. Os itens abaixo são apenas parecidos: "
                        "confirme com o cliente antes de falar de qualquer um deles como se fosse o pedido."),
            "candidates": [self._summary(r) for _, r in partial[:5]],
        }

    def _detail(self, row) -> dict:
        final, promo = self._final_price(row)
        availability = self._availability(row)
        pix = pricing.pix_price(row["price_brl"], promo is not None)
        options = pricing.installment_options(final)
        expired = self.db.query(
            "SELECT description, discount_percent FROM promotions WHERE product_id = ? AND is_active = 0",
            (row["product_id"],),
        )
        out = {
            "match": "exact",
            "product_id": row["product_id"],
            "name": row["name"],
            "brand": row["brand"],
            "category": self.categories[row["category_id"]],
            "availability": AVAILABILITY_PT[availability],
            "stock_quantity": row["stock_quantity"],
            "description": row["description"],
            "specs": json.loads(row["specs"]),
            "pricing": {
                "list_price": pricing.fmt_brl(row["price_brl"]),
                "active_promotion": (
                    {"name": promo["description"], "discount_percent": int(promo["discount_percent"]),
                     "price_with_promotion": pricing.fmt_brl(final)}
                    if promo else None
                ),
                "final_price": pricing.fmt_brl(final),
                "pix": (
                    {"price": pricing.fmt_brl(pix), "rule": "5% de desconto sobre o preço de tabela"}
                    if pix is not None
                    else {"price": None, "rule": "sem desconto PIX: o produto já está em promoção e os descontos não se acumulam"}
                ),
                "credit_card": {
                    "max_installments": len(options),
                    "options": [f"{n}x de {pricing.fmt_brl(v)}" for n, v in options],
                    "rule": "sem juros; 4x a 6x com parcela mínima de R$ 80,00; 7x a 12x com parcela mínima de R$ 100,00",
                },
                "combined_payment_allowed": pricing.combined_payment_allowed(final),
            },
            "expired_promotions": [
                {"name": e["description"], "discount_percent": int(e["discount_percent"]), "status": "encerrada"}
                for e in expired
            ],
        }
        if row["description"] is None:
            out["description_note"] = "Descrição de cadastro inconsistente com o produto; use só nome e especificações."
        if availability != "in_stock":
            out["alternatives"] = self._alternatives(row)
        return out

    def quote_order(self, items: list[dict], city: str | None = None) -> dict:
        if not items:
            return {"error": "informe ao menos um item (product_id e quantity)"}
        lines, warnings = [], []
        subtotal = Decimal("0")
        pix_total = Decimal("0")
        any_promo = False
        for item in items:
            pid = int(item.get("product_id", 0))
            qty = int(item.get("quantity", 1) or 1)
            row = self.db.one("SELECT * FROM products WHERE product_id = ?", (pid,))
            if row is None or qty < 1:
                return {"error": f"produto {pid} não encontrado ou quantidade inválida"}
            availability = self._availability(row)
            if availability != "in_stock":
                warnings.append(f"{row['name']}: {AVAILABILITY_PT[availability]}")
            elif qty > row["stock_quantity"]:
                warnings.append(f"{row['name']}: só há {row['stock_quantity']} em estoque")
            unit, promo = self._final_price(row)
            any_promo |= promo is not None
            line_total = unit * qty
            subtotal += line_total
            pix_unit = pricing.pix_price(row["price_brl"], promo is not None)
            pix_total += (pix_unit if pix_unit is not None else unit) * qty
            lines.append({"product_id": pid, "name": row["name"], "quantity": qty,
                          "unit_price": pricing.fmt_brl(unit), "line_total": pricing.fmt_brl(line_total),
                          "on_promotion": promo is not None})

        shipping: dict
        fee = None
        if not city:
            shipping = {"status": "informe a cidade de entrega para calcular o frete"}
        elif pricing.is_metro_city(city):
            fee = pricing.metro_shipping_fee(subtotal)
            shipping = {"region": "Região Metropolitana de Campo Grande", "fee": pricing.fmt_brl(fee),
                        "rule": "grátis acima de R$ 500,00; abaixo disso, taxa fixa de R$ 35,00",
                        "delivery_time": "1 a 3 dias úteis, por motoboy próprio"}
        else:
            shipping = {"region": "outras cidades", "fee": None,
                        "rule": "calculado pelo CEP de destino, peso e dimensões (Correios PAC/SEDEX ou Jadlog); "
                                "o atendimento humano faz a cotação",
                        "options": ["PAC: 5 a 12 dias úteis", "SEDEX: 2 a 5 dias úteis", "Jadlog: 3 a 8 dias úteis"]}

        total = subtotal + (fee or 0)
        out = {
            "items": lines,
            "subtotal": pricing.fmt_brl(subtotal),
            "shipping": shipping,
            "total": pricing.fmt_brl(total) if fee is not None else None,
            "total_note": None if fee is not None else "total sem frete; o frete depende da cidade/CEP",
            "pix_total": pricing.fmt_brl(pix_total + (fee or 0)) if pix_total < subtotal else None,
            "pix_note": ("5% de desconto PIX só nos itens sem promoção; frete sem desconto"
                         if pix_total < subtotal else "sem desconto PIX: todos os itens já estão em promoção"),
        }
        base = total if fee is not None else subtotal
        n = pricing.max_installments(base)
        out["credit_card"] = {
            "max_installments": n,
            "options": [f"{k}x de {pricing.fmt_brl(v)}" for k, v in pricing.installment_options(base)],
            "computed_on": "total com frete" if fee is not None else "subtotal (sem frete)",
        }
        out["combined_payment_allowed"] = pricing.combined_payment_allowed(base)
        if warnings:
            out["warnings"] = warnings
        return out

    def list_active_promotions(self, category: str | None = None) -> dict:
        rows = self.db.query(
            "SELECT p.*, pr.description AS promo_name, pr.discount_percent FROM promotions pr "
            "JOIN products p ON p.product_id = pr.product_id WHERE pr.is_active = 1 ORDER BY pr.discount_percent DESC"
        )
        category_id = self._category_id(category) if category else None
        if category and category_id is None:
            return {"error": f"unknown category '{category}'", "categories": list(self.categories.values())}
        promos = []
        for row in rows:
            cat = self.categories[row["category_id"]]
            if category_id and row["category_id"] != category_id:
                continue
            promos.append({
                "product_id": row["product_id"],
                "name": row["name"],
                "category": cat,
                "promotion": row["promo_name"],
                "discount_percent": int(row["discount_percent"]),
                "original_price": pricing.fmt_brl(row["price_brl"]),
                "price_with_promotion": pricing.fmt_brl(
                    pricing.promotional_price(row["price_brl"], row["discount_percent"])),
                "availability": AVAILABILITY_PT[self._availability(row)],
            })
        return {
            "active_promotions": promos,
            "rules": "promoções não se acumulam; sem desconto PIX em produto promocional; "
                     "sujeitas ao estoque, sem reserva de preço",
        }

    # ------------------------------------------------------------------ tools: orders

    def _verify(self, order_id, contact: str):
        """Return the order row if ``contact`` (e-mail or phone) belongs to its customer."""
        if self.verification_failures >= MAX_VERIFICATION_FAILURES:
            return None, {
                "verified": False,
                "error": "verificação bloqueada nesta conversa após várias tentativas sem sucesso",
                "next_step": f"encaminhar ao atendimento humano: WhatsApp {STORE_WHATSAPP} ou {STORE_EMAIL}",
            }
        try:
            order_id = int(str(order_id).strip().lstrip("#"))
        except ValueError:
            order_id = -1
        row = self.db.one(
            "SELECT o.*, c.first_name, c.email_norm, c.phone_digits FROM orders o "
            "JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_id = ?",
            (order_id,),
        )
        contact = (contact or "").strip()
        ok = False
        if row is not None and contact:
            if "@" in contact:
                ok = contact.lower() == row["email_norm"]
            else:
                digits = phone_digits(contact)
                ok = len(digits) >= 9 and row["phone_digits"].endswith(digits)
        if not ok:
            self.verification_failures += 1
            # Same answer for "no such order" and "wrong contact": do not reveal which orders exist.
            return None, {
                "verified": False,
                "error": "número do pedido e e-mail/telefone não conferem com o cadastro",
                "attempts_left": MAX_VERIFICATION_FAILURES - self.verification_failures,
            }
        return row, None

    def _items(self, order_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT p.name, p.product_id, i.quantity FROM order_items i JOIN products p ON p.product_id = i.product_id "
            "WHERE i.order_id = ?",
            (order_id,),
        )
        return [{"product_id": r["product_id"], "name": r["name"], "quantity": r["quantity"]} for r in rows]

    def get_order_status(self, order_id: int, contact: str) -> dict:
        row, failure = self._verify(order_id, contact)
        if failure:
            return failure
        today = self.now().date()
        eta = _parse_date(row["estimated_delivery"])
        out = {
            "verified": True,
            "order_id": row["order_id"],
            "customer_first_name": row["first_name"],
            "status": row["status"],
            "status_label": ORDER_STATUS_PT[row["status"]],
            "order_date": _fmt_date(_parse_date(row["order_date"])),
            "total": pricing.fmt_brl(row["total_brl"]),
            "payment": _payment_label(row["payment_method"]),
            "items": self._items(row["order_id"]),
        }
        if row["tracking_code"]:
            out["tracking_code"] = row["tracking_code"]
            out["tracking_where"] = "site dos Correios ou da Jadlog"
        if row["status"] == "shipped" and eta:
            out["estimated_delivery"] = _fmt_date(eta)
            late = (today - eta).days
            out["is_late"] = late > 0
            if late > 0:
                out["days_late"] = late
                out["next_step"] = "pedir desculpas e oferecer encaminhar ao atendimento humano para verificar com a transportadora"
        if row["status"] == "delivered" and eta:
            out["delivered_on"] = _fmt_date(eta)
            out["delivered_on_note"] = "data considerada como a de entrega prevista (o sistema não registra a data real)"
        if row["status"] == "cancelled":
            out["cancellation_reason"] = row["notes"]
        if row["status"] in ("pending", "confirmed"):
            out["next_step"] = "o código de rastreio é enviado por e-mail e WhatsApp quando o pedido for despachado"
        return out

    def check_return_eligibility(self, order_id: int, contact: str, reason: str) -> dict:
        reason = strip_accents((reason or "").strip().lower())
        if reason not in RETURN_REASONS:
            return {"error": f"reason deve ser um de {RETURN_REASONS}"}
        row, failure = self._verify(order_id, contact)
        if failure:
            return failure

        status = row["status"]
        base = {"verified": True, "order_id": row["order_id"], "customer_first_name": row["first_name"],
                "order_status": ORDER_STATUS_PT[status], "items": self._items(row["order_id"]),
                "payment": _payment_label(row["payment_method"])}
        if status == "cancelled":
            return base | {"eligible": False, "explanation": "o pedido foi cancelado; não há produto a devolver",
                           "cancellation_reason": row["notes"]}
        if status in ("pending", "confirmed"):
            return base | {
                "eligible": None,
                "explanation": "o pedido ainda não foi enviado; o manual não trata cancelamento antes do envio",
                "next_step": "encaminhar ao atendimento humano (escalate_to_human) para avaliar o cancelamento",
            }

        today = self.now().date()
        received_on = _parse_date(row["estimated_delivery"]) if status == "delivered" else None
        result = rules.evaluate_return(reason, _parse_date(row["order_date"]), received_on, today)
        counted_from = "do recebimento" if result["counted_from"] == "receipt" else "da compra"

        out = base | {
            "reason": reason,
            "eligible": result["eligible"],
            "window": f"{result['window_days']} dias corridos a partir {counted_from}",
            "order_date": _fmt_date(_parse_date(row["order_date"])),
            "received_on": _fmt_date(received_on),
            "deadline": _fmt_date(result["deadline"]),
            "days_elapsed": result["days_elapsed"],
            "days_left": result["days_left"],
        }
        if received_on:
            out["received_on_note"] = "data de entrega prevista, assumida como data de recebimento"
        if result["eligible"] is None:
            out["explanation"] = ("o pedido ainda não foi recebido; o prazo começa a contar no recebimento. "
                                  "Em caso de avaria no transporte, recusar o recebimento e avisar a loja.")
        elif result["eligible"]:
            out["explanation"] = f"dentro do prazo: até {_fmt_date(result['deadline'])}"
        else:
            out["explanation"] = (f"fora do prazo: o limite era {_fmt_date(result['deadline'])} "
                                  f"({result['days_elapsed']} dias se passaram)")

        out["conditions"] = {
            "arrependimento": ["produto na embalagem original, sem sinais de uso, com acessórios e manuais",
                               "reembolso na mesma forma de pagamento em até 10 dias úteis",
                               "frete de devolução por conta da loja"],
            "preferencia": ["produto em perfeito estado e na embalagem original",
                            "sujeito à disponibilidade do produto desejado",
                            "diferenças de valor cobradas ou reembolsadas"],
            "defeito": ["defeito de fabricação; mau uso, quedas, umidade ou modificações não são cobertos"],
        }[reason]
        out["not_eligible_items"] = ["instrumentos com personalização ou ajuste sob encomenda",
                                     "liquidação com aviso de 'venda final'", "boquilhas de instrumentos de sopro"]

        alternatives = []
        warranty = result["legal_warranty"]
        if warranty["active"]:
            alternatives.append(
                f"se houver defeito de fabricação: garantia legal de 90 dias a partir do recebimento, "
                f"válida até {_fmt_date(warranty['until'])}")
        elif warranty["active"] is False:
            alternatives.append(f"garantia legal de 90 dias encerrada em {_fmt_date(warranty['until'])}")
        alternatives.append("garantia do fabricante (em geral de 6 meses a 2 anos, conforme o certificado do produto); "
                            "a loja pode intermediar o acionamento")
        if result["eligible"] is False or reason == "defeito":
            out["alternatives"] = alternatives
        return out

    # ------------------------------------------------------------------ tools: store

    def get_store_status(self) -> dict:
        now = self.now()
        status = rules.store_status(now)
        nxt = status["next_opening"]
        return {
            "now": f"{rules.WEEKDAYS_PT[now.weekday()]}, {now:%d/%m/%Y %H:%M} (horário de Campo Grande/MS)",
            "is_open": status["is_open"],
            "today_hours": status["today_hours"],
            "holiday": status["holiday"],
            "closes_at": status["closes_at"],
            "next_opening": f"{rules.WEEKDAYS_PT[nxt.weekday()]}, {nxt:%d/%m/%Y às %H:%M}" if nxt else None,
            "weekly_hours": {"segunda a sexta": "09:00 às 18:00", "sábado": "09:00 às 13:00",
                             "domingo e feriados": "fechado"},
            "note": "em datas especiais (Black Friday, aniversário da loja, Natal) o horário pode ser estendido",
        }

    def escalate_to_human(
        self,
        summary: str,
        reason: str = "outro",
        customer_contact: str | None = None,
        customer_name: str | None = None,
        order_id: int | None = None,
    ) -> dict:
        now = self.now()
        self.handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        existing = 0
        if self.handoffs_file.exists():
            existing = sum(1 for _ in self.handoffs_file.open(encoding="utf-8"))
        protocol = f"EM-{now:%Y%m%d}-{existing + 1:04d}"
        record = {
            "protocol": protocol,
            "created_at": now.isoformat(timespec="seconds"),
            "reason": reason if reason in ESCALATION_REASONS else "outro",
            "summary": summary,
            "customer_name": customer_name,
            "customer_contact": customer_contact,
            "order_id": order_id,
        }
        with self.handoffs_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        status = rules.store_status(now)
        return {
            "protocol": protocol,
            "return_deadline": "até 24 horas úteis",
            "team_available_now": status["is_open"],
            "contact_needed": customer_contact is None,
            "channels": {"whatsapp": STORE_WHATSAPP, "telefone": STORE_PHONE, "email": STORE_EMAIL},
        }


# ---------------------------------------------------------------------- declarations for the model

_CATEGORY_NAMES = [
    "Guitarras", "Baixos", "Baterias e Percussão", "Teclados e Pianos", "Violões",
    "Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)", "Cordas Orquestrais", "Ukuleles",
]
_ORDER_ARGS = {
    "order_id": {"type": "integer", "description": "Número do pedido informado pelo cliente."},
    "contact": {"type": "string", "description": "E-mail ou telefone do cliente, exatamente como ele informou."},
}

TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "search_products",
        "description": (
            "Busca no catálogo de instrumentos. Use para perguntas abertas ('quais violões até R$ 1000?', "
            "'tem ukulele com captação?'). Devolve preço final (com promoção ativa), preço no PIX, parcelamento "
            "máximo e estoque. Por padrão só traz o que pode ser comprado agora e lista à parte o que bate com a "
            "busca mas está esgotado, descontinuado ou em breve."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Palavras-chave: marca, modelo ou característica (ex.: 'captação', 'nylon', '7 cordas'). Não repita aqui a categoria nem o preço."},
                "category": {"type": "string", "enum": _CATEGORY_NAMES},
                "min_price": {"type": "number", "description": "Preço final mínimo em reais."},
                "max_price": {"type": "number", "description": "Preço final máximo em reais."},
                "include_unavailable": {"type": "boolean", "description": "Incluir esgotados, descontinuados e em breve. Padrão: false."},
            },
        },
    },
    {
        "name": "get_product",
        "description": (
            "Detalhe de UM produto pelo nome ou código: preço de tabela, promoção ativa, preço no PIX, todas as "
            "opções de parcelamento, estoque, especificações, promoções encerradas e alternativas quando estiver "
            "indisponível. Se o nome for ambíguo ou só parecido, devolve candidatos: pergunte ao cliente qual é."
        ),
        "parameters": {
            "type": "object",
            "properties": {"product": {"type": "string", "description": "Nome (ex.: 'Takamine GD20') ou código do produto."}},
            "required": ["product"],
        },
    },
    {
        "name": "quote_order",
        "description": (
            "Calcula um orçamento: subtotal, frete, total, total no PIX e parcelamento. Use quando o cliente "
            "quiser saber o frete ou comprar mais de um item/quantidade. Precisa dos product_id (obtenha antes "
            "com get_product ou search_products)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"product_id": {"type": "integer"}, "quantity": {"type": "integer"}},
                        "required": ["product_id", "quantity"],
                    },
                },
                "city": {"type": "string", "description": "Cidade de entrega, se o cliente informou."},
            },
            "required": ["items"],
        },
    },
    {
        "name": "list_active_promotions",
        "description": (
            "Lista as promoções ativas agora, com preço original, desconto e preço promocional. Para um "
            "produto específico, use get_product: ele mostra as promoções ativas e encerradas daquele "
            "produto, o estoque e as alternativas."
        ),
        "parameters": {"type": "object", "properties": {"category": {"type": "string", "enum": _CATEGORY_NAMES}}},
    },
    {
        "name": "get_order_status",
        "description": (
            "Status de um pedido (situação, itens, rastreio, previsão, motivo de cancelamento). Exige o número do "
            "pedido E o e-mail ou telefone do cliente; peça os dois antes de chamar. Nunca revele dados se a "
            "verificação falhar."
        ),
        "parameters": {"type": "object", "properties": _ORDER_ARGS, "required": ["order_id", "contact"]},
    },
    {
        "name": "check_return_eligibility",
        "description": (
            "Verifica se um pedido pode ser devolvido ou trocado, contando os dias contra os prazos do manual "
            "(arrependimento: 7 dias do recebimento; defeito: 30 dias da compra; preferência: 7 dias do "
            "recebimento) e indica alternativas (garantia legal, garantia do fabricante). Exige número do pedido "
            "e e-mail ou telefone."
        ),
        "parameters": {
            "type": "object",
            "properties": _ORDER_ARGS | {
                "reason": {"type": "string", "enum": RETURN_REASONS,
                           "description": "arrependimento = desistiu da compra; defeito = problema de fabricação; preferencia = trocar cor/modelo/tamanho."},
            },
            "required": ["order_id", "contact", "reason"],
        },
    },
    {
        "name": "get_store_status",
        "description": "Data e hora atuais em Campo Grande/MS, se a loja está aberta agora, horário de hoje e próxima abertura.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Registra um encaminhamento para a equipe humana e devolve um protocolo (retorno em até 24 horas "
            "úteis). Use para reclamações, cancelamentos, cotação de frete por CEP, pedidos atrasados e qualquer "
            "pergunta que o manual e os dados não respondam. Peça antes um contato (telefone ou e-mail)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Resumo objetivo do caso, em português."},
                "reason": {"type": "string", "enum": ESCALATION_REASONS},
                "customer_contact": {"type": "string"},
                "customer_name": {"type": "string"},
                "order_id": {"type": "integer"},
            },
            "required": ["summary", "reason"],
        },
    },
]
TOOL_NAMES = {d["name"] for d in TOOL_DECLARATIONS}
