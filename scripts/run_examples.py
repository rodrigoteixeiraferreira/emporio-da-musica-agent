"""Run the example scenarios against the real model and write examples/*.md.

The files are the raw output of this script: never edit them by hand. To change an
example, change the code or the prompt and run the script again.

Usage:
    python scripts/run_examples.py                      # all scenarios, default model
    python scripts/run_examples.py --only 3 5           # some scenarios
    python scripts/run_examples.py --model gemini-3.5-flash-lite --out-dir /tmp/dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


from emporio_agent.agent import Agent
from emporio_agent.cli import force_utf8_console
from emporio_agent.config import PROJECT_ROOT, STORE_TZ, gemini_model, load_env
from emporio_agent.db import StoreDB
from emporio_agent.tools import StoreTools

REFERENCE_TIME = "2026-03-25T10:00"  # a Wednesday, three days after the last order in the data

SCENARIOS = [
    {
        "id": 1, "slug": "catalog-search", "title": "Catalog search with a price ceiling",
        "goal": "Open catalog question: filter by category and price, hide unavailable items but mention them.",
        "messages": ["Quais opções de violões disponíveis custando até R$1000?"],
    },
    {
        "id": 2, "slug": "price-and-payment", "title": "Price, installments and PIX",
        "goal": "Price of a specific product, a 10x installment check and the PIX discount, all computed by tools.",
        "messages": ["Quanto custa o Takamine GD20? Dá pra parcelar em 10x? E no PIX sai mais barato?"],
    },
    {
        "id": 3, "slug": "return-request", "title": "Return request (non-trivial: verification + policy dates)",
        "goal": "The agent asks for the order number and e-mail, verifies them, counts the days against the "
                "7-day regret window and explains the alternatives once the window has passed.",
        "messages": [
            "Oi! Me arrependi da minha compra, posso devolver meu pedido?",
            "O pedido é o 7 e meu e-mail é leticia.rocha@jmail.com",
            "Poxa. E se o ukulele apresentar algum defeito, o que eu faço?",
        ],
    },
    {
        "id": 4, "slug": "out-of-scope", "title": "Accessories and an unrelated question",
        "goal": "Accessories are politely declined (the store sells instruments only) and an unrelated "
                "question gets a short answer that steers back to the store.",
        "messages": [
            "Vocês vendem cordas e amplificador?",
            "Entendi. Aproveitando, quem ganhou a Copa do Mundo de 2022?",
        ],
    },
    {
        "id": 5, "slug": "expired-promotion-out-of-stock", "title": "Expired promotion on an out-of-stock product",
        "goal": "The customer asks for a past promotion on a product that is out of stock: the agent says the "
                "promotion has ended, that the product is unavailable, offers alternatives and quotes shipping.",
        "messages": [
            "Vi que o violão Giannini GF-3D estava com 40% de desconto na Semana do Músico. Ainda tá valendo? Queria comprar um.",
            "Gostei do primeiro que você sugeriu. Moro em Campo Grande, quanto fica com a entrega?",
        ],
    },
]


def git_commit() -> str:
    def run(*args):
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()
    commit = run("rev-parse", "--short", "HEAD") or "unknown"
    return commit + ("-dirty" if run("status", "--porcelain", "--untracked-files=no") else "")


def render(scenario: dict, model: str, turns: list[tuple[str, object]], requests: int) -> str:
    lines = [
        f"# Example {scenario['id']} — {scenario['title']}",
        "",
        "| | |",
        "|---|---|",
        f"| Scenario | {scenario['goal']} |",
        f"| Model | `{model}` (Gemini API, free tier) |",
        f"| Reference date (`STORE_TODAY`) | {REFERENCE_TIME} (America/Campo_Grande) |",
        f"| Generated at | {datetime.now(STORE_TZ).isoformat(timespec='seconds')} |",
        f"| Commit | `{git_commit()}` |",
        f"| Model requests | {requests} |",
        "",
        "> Raw output of `scripts/run_examples.py`, not edited by hand. The conversation is in Brazilian "
        "Portuguese; tool calls are shown as with `--show-tools` (expand to see what each tool returned).",
        "",
    ]
    for user_text, reply in turns:
        lines += [f"**Cliente:** {user_text}", ""]
        for call in reply.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in call.args.items())
            lines += [
                "<details>",
                f"<summary>🔧 <code>{call.name}({args})</code></summary>",
                "",
                "```json",
                json.dumps(call.result, ensure_ascii=False, indent=2),
                "```",
                "</details>",
                "",
            ]
        body = reply.text.replace("\n", "  \n")
        lines += [f"**Loja:** {body}", ""]
    return "\n".join(lines)


def main() -> int:
    force_utf8_console()
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None, help="Gemini model id (default: GEMINI_MODEL or gemini-3.8-flash)")
    parser.add_argument("--only", type=int, nargs="*", help="scenario ids to run")
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "examples")
    parser.add_argument("--min-interval", type=float, default=13.0,
                        help="seconds between model requests (free-tier Flash allows 5 per minute)")
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1
    os.environ["STORE_TODAY"] = REFERENCE_TIME
    model = args.model or gemini_model()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    db = StoreDB()

    for scenario in SCENARIOS:
        if args.only and scenario["id"] not in args.only:
            continue
        agent = Agent(StoreTools(db), model=model, min_interval_s=args.min_interval)
        turns = []
        print(f"[{scenario['id']}] {scenario['title']}")
        for message in scenario["messages"]:
            reply = agent.send(message)
            turns.append((message, reply))
            print(f"  cliente: {message}\n  tools: {[c.name for c in reply.tool_calls]}\n  loja: {reply.text}\n")
        path = args.out_dir / f"{scenario['id']:02d}-{scenario['slug']}.md"
        path.write_text(render(scenario, model, turns, agent.total_requests), encoding="utf-8", newline="\n")
        print(f"  -> {path} ({agent.total_requests} requests)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
