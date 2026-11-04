"""Command-line chat with the agent.

    python -m emporio_agent [--show-tools] [--model MODEL] [--today 2026-03-25T10:00]

Inside the chat: /reset starts a new conversation, /sair (or /exit) quits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from google.genai import errors

from .agent import Agent, DailyQuotaExceeded, ToolCall
from .config import gemini_model, load_env, store_now
from .db import StoreDB
from .prompts import now_label
from .tools import StoreTools


def force_utf8_console() -> None:
    """Windows consoles may default to cp1252/cp850; Portuguese accents need UTF-8."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def describe_tool_call(call: ToolCall, max_result_chars: int = 400) -> str:
    args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in call.args.items())
    result = json.dumps(call.result, ensure_ascii=False)
    if len(result) > max_result_chars:
        result = result[: max_result_chars - 3] + "..."
    return f"{call.name}({args}) -> {result}"


def main(argv: list[str] | None = None) -> int:
    force_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m emporio_agent", description="Chat with the Empório da Música agent.")
    parser.add_argument("--show-tools", action="store_true", help="print every tool call and its result")
    parser.add_argument("--model", help="Gemini model id (default: GEMINI_MODEL or gemini-3.6-flash)")
    parser.add_argument("--today", help="reference date/time for the store, e.g. 2026-03-25T10:00 (overrides STORE_TODAY)")
    args = parser.parse_args(argv)

    load_env()
    if args.today:
        os.environ["STORE_TODAY"] = args.today
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set. Copy .env.example to .env and add your free key "
              "(https://aistudio.google.com -> Get API key).", file=sys.stderr)
        return 1

    show = (lambda call: print(f"  [tool] {describe_tool_call(call)}")) if args.show_tools else None
    tools = StoreTools(StoreDB())
    agent = Agent(tools, model=args.model or gemini_model(), on_tool_call=show)

    print(f"Empório da Música - assistente virtual | modelo {agent.model} | agora: {now_label(store_now())}")
    print("Digite sua mensagem. /reset recomeça a conversa, /sair encerra.\n")
    while True:
        try:
            text = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in ("/sair", "/exit", "/quit"):
            return 0
        if text.lower() == "/reset":
            agent.reset()
            print("(conversa reiniciada)\n")
            continue
        try:
            reply = agent.send(text)
        except DailyQuotaExceeded as exc:
            print(f"[erro] {exc}", file=sys.stderr)
            continue
        except errors.APIError as exc:
            print(f"[erro da API Gemini {exc.code}] {exc.message}", file=sys.stderr)
            continue
        print(f"loja> {reply.text}\n")
