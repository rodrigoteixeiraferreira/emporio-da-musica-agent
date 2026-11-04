# Example 5 — Expired promotion on an out-of-stock product

| | |
|---|---|
| Scenario | The customer asks for a past promotion on a product that is out of stock: the agent says the promotion has ended, that the product is unavailable, offers alternatives and quotes shipping. |
| Model | `gemini-3.6-flash` (Gemini API, free tier) |
| Reference date (`STORE_TODAY`) | 2026-03-25T10:00 (America/Campo_Grande) |
| Generated at | 2026-11-04T10:37:46-04:00 |
| Commit | `49e44f5` |
| Model requests | 4 |

> Raw output of `scripts/run_examples.py`, not edited by hand. The conversation is in Brazilian Portuguese; tool calls are shown as with `--show-tools` (expand to see what each tool returned).

**Cliente:** Vi que o violão Giannini GF-3D estava com 40% de desconto na Semana do Músico. Ainda tá valendo? Queria comprar um.

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
      "product_id": 101,
      "name": "Giannini GNF-3 CEQ Elétrico Nylon Natural",
      "category": "Violões",
      "availability": "disponível",
      "stock_quantity": 4,
      "price": "R$ 1.049,00",
      "pix_price": "R$ 996,55",
      "max_installments": "10x de R$ 104,90 sem juros"
    },
    {
      "product_id": 97,
      "name": "Crafter D-8 Dreadnought Natural",
      "category": "Violões",
      "availability": "disponível",
      "stock_quantity": 2,
      "price": "R$ 4.599,00",
      "pix_price": "R$ 4.369,05",
      "max_installments": "12x de R$ 383,25 sem juros"
    }
  ]
}
```
</details>

**Loja:** Olá! A promoção da Semana do Músico já se encerrou, então o desconto não está mais ativo.   
  
O violão Giannini GF-3D Dreadnought Sunburst voltou ao preço normal de R$ 799,90 (ou R$ 759,91 no PIX, ou em até 7x de R$ 114,27 sem juros), mas no momento ele está esgotado no nosso estoque.  
  
Se quiser ver outras opções disponíveis na loja, tenho estas alternativas:  
- Giannini GF-1R Aço Folk Sunburst por R$ 579,90 (ou R$ 550,91 no PIX)  
- Giannini GNF-3 CEQ Elétrico Nylon Natural por R$ 1.049,00 (ou R$ 996,55 no PIX)  
- Crafter D-8 Dreadnought Natural por R$ 4.599,00 (ou R$ 4.369,05 no PIX)  
  
Posso te ajudar com mais detalhes sobre algum desses modelos ou com alguma outra dúvida?

**Cliente:** Gostei do primeiro que você sugeriu. Moro em Campo Grande, quanto fica com a entrega?

<details>
<summary>🔧 <code>quote_order(city="Campo Grande", items=[{"quantity": 1, "product_id": 88}])</code></summary>

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

**Loja:** Ótima escolha! Para o violão Giannini GF-1R Aço Folk Sunburst, como o valor é de R$ 579,90 (acima de R$ 500,00), o frete para Campo Grande é grátis! 🚛  
  
O prazo de entrega é de 1 a 3 dias úteis via motoboy próprio.   
  
O valor total do pedido fica em R$ 579,90, com desconto no PIX saindo por R$ 550,91, ou parcelado no cartão em até 6x de R$ 96,65 sem juros.  
  
Posso te ajudar a dar andamento ou em mais alguma dúvida?
