# Example 5 — Expired promotion on an out-of-stock product

| | |
|---|---|
| Scenario | The customer asks for a past promotion on a product that is out of stock: the agent says the promotion has ended, that the product is unavailable, offers alternatives and quotes shipping. |
| Model | `gemini-3-flash-preview` (Gemini API, free tier) |
| Reference date (`STORE_TODAY`) | 2026-03-25T10:00 (America/Campo_Grande) |
| Generated at | 2026-11-04T10:40:37-04:00 |
| Commit | `64eccc8` |
| Model requests | 4 |

> Raw output of `scripts/run_examples.py`, not edited by hand. The conversation is in Brazilian Portuguese; tool calls are shown as with `--show-tools` (expand to see what each tool returned).

**Cliente:** Vi que o violão Giannini GF-3D estava com 40% de desconto na Semana do Músico. Ainda tá valendo? Queria comprar um.

<details>
<summary>🔧 <code>get_store_status()</code></summary>

```json
{
  "now": "quarta-feira, 25/03/2026 10:00 (horário de Campo Grande/MS)",
  "is_open": true,
  "today_hours": "09:00 às 18:00",
  "holiday": null,
  "closes_at": "18:00",
  "next_opening": null,
  "weekly_hours": {
    "segunda a sexta": "09:00 às 18:00",
    "sábado": "09:00 às 13:00",
    "domingo e feriados": "fechado"
  },
  "note": "em datas especiais (Black Friday, aniversário da loja, Natal) o horário pode ser estendido"
}
```
</details>

<details>
<summary>🔧 <code>get_product(product="Giannini GF-3D")</code></summary>

```json
{
  "match": "exact",
  "product_id": 96,
  "name": "Giannini GF-3D Dreadnought Sunburst",
  "brand": "Giannini",
  "category": "Violões",
  "availability": "esgotado (temporariamente indisponível)",
  "stock_quantity": 0,
  "description": "Violão dreadnought com corpo amplo e acabamento Sunburst. Volume alto e graves profundos, ideal para country e pop.",
  "specs": {
    "top": "Spruce",
    "back_sides": "Sapele",
    "neck": "Nato",
    "strings": "steel",
    "scale": "650mm",
    "electronics": "no",
    "color": "Sunburst"
  },
  "pricing": {
    "list_price": "R$ 799,90",
    "active_promotion": null,
    "final_price": "R$ 799,90",
    "pix": {
      "price": "R$ 759,91",
      "rule": "5% de desconto sobre o preço de tabela"
    },
    "credit_card": {
      "max_installments": 7,
      "options": [
        "1x de R$ 799,90",
        "2x de R$ 399,95",
        "3x de R$ 266,63",
        "4x de R$ 199,98",
        "5x de R$ 159,98",
        "6x de R$ 133,32",
        "7x de R$ 114,27"
      ],
      "rule": "sem juros; 4x a 6x com parcela mínima de R$ 80,00; 7x a 12x com parcela mínima de R$ 100,00"
    },
    "combined_payment_allowed": false
  },
  "expired_promotions": [
    {
      "name": "Semana do Músico",
      "discount_percent": 18,
      "status": "encerrada"
    },
    {
      "name": "Semana do Músico",
      "discount_percent": 40,
      "status": "encerrada"
    }
  ],
  "alternatives": [
    {
      "product_id": 88,
      "name": "Giannini GF-1R Aço Folk Sunburst",
      "category": "Violões",
      "availability": "disponível",
      "stock_quantity": 7,
      "price": "R$ 579,90",
      "pix_price": "R$ 550,91",
      "max_installments": "6x de R$ 96,65 sem juros"
    },
    {
      "product_id": 107,
      "name": "Shelby SGD-195E Elétrico Aço Sunburst",
      "category": "Violões",
      "availability": "disponível",
      "stock_quantity": 6,
      "price": "R$ 799,00",
      "pix_price": "R$ 759,05",
      "max_installments": "7x de R$ 114,14 sem juros"
    },
    {
      "product_id": 91,
      "name": "Tagima Woodstock Dreadnought Natural",
      "category": "Violões",
      "availability": "disponível",
      "stock_quantity": 11,
      "price": "R$ 899,00",
      "pix_price": "R$ 854,05",
      "max_installments": "8x de R$ 112,38 sem juros"
    }
  ]
}
```
</details>

**Loja:** Olá! Tudo bem? A promoção da Semana do Músico já encerrou, então aquele desconto de 40% não está mais ativo.   
  
No momento, o violão Giannini GF-3D Dreadnought Sunburst está saindo por R$ 799,90 (ou R$ 759,91 no PIX com 5% de desconto). Além disso, ele está temporariamente esgotado em nosso estoque.  
  
Como você busca um modelo parecido, tenho estas opções disponíveis agora:  
- Giannini GF-1R Aço Folk Sunburst: R$ 579,90 (ou R$ 550,91 no PIX).  
- Shelby SGD-195E Elétrico Aço Sunburst: R$ 799,00 (ou R$ 759,05 no PIX).  
- Tagima Woodstock Dreadnought Natural: R$ 899,00 (ou R$ 854,05 no PIX).  
  
Algum desses te interessa ou gostaria de ver outro modelo?

**Cliente:** Gostei do primeiro que você sugeriu. Moro em Campo Grande, quanto fica com a entrega?

<details>
<summary>🔧 <code>quote_order(items=[{"quantity": 1, "product_id": 88}], city="Campo Grande")</code></summary>

```json
{
  "items": [
    {
      "product_id": 88,
      "name": "Giannini GF-1R Aço Folk Sunburst",
      "quantity": 1,
      "unit_price": "R$ 579,90",
      "line_total": "R$ 579,90",
      "on_promotion": false
    }
  ],
  "subtotal": "R$ 579,90",
  "shipping": {
    "region": "Região Metropolitana de Campo Grande",
    "fee": "R$ 0,00",
    "rule": "grátis acima de R$ 500,00; abaixo disso, taxa fixa de R$ 35,00",
    "delivery_time": "1 a 3 dias úteis, por motoboy próprio"
  },
  "total": "R$ 579,90",
  "total_note": null,
  "pix_total": "R$ 550,91",
  "pix_note": "5% de desconto PIX só nos itens sem promoção; frete sem desconto",
  "credit_card": {
    "max_installments": 6,
    "options": [
      "1x de R$ 579,90",
      "2x de R$ 289,95",
      "3x de R$ 193,30",
      "4x de R$ 144,98",
      "5x de R$ 115,98",
      "6x de R$ 96,65"
    ],
    "computed_on": "total com frete"
  },
  "combined_payment_allowed": false
}
```
</details>

**Loja:** Como o valor do Giannini GF-1R é de R$ 579,90, a sua entrega aqui em Campo Grande sai de graça! Nossa política oferece frete grátis para pedidos acima de R$ 500,00 na cidade.  
  
O total do pedido fica em R$ 579,90, e se você optar pelo PIX, tem aquele desconto de 5% e o valor cai para R$ 550,91. No cartão, você pode parcelar em até 6x de R$ 96,65 sem juros.  
  
O prazo de entrega pelo nosso motoboy é de 1 a 3 dias úteis. Gostaria de fechar o pedido ou tem mais alguma dúvida?
