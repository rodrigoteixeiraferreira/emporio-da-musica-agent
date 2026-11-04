"""Guards on the generated example conversations (no network).

1. Every tool call recorded in examples/*.md is re-run against the current code with the
   example's reference time, and must return exactly the JSON shown in the file. So the examples
   stay true even when they were generated at an older commit.
2. Every amount in R$ that the store states must appear in a tool result (or tool argument) of
   the same conversation, or in the customer's own message: "numbers come from tools, not from
   the model", checked mechanically.
"""

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_agent.config import PROJECT_ROOT, STORE_TZ
from emporio_agent.tools import StoreTools

EXAMPLES = sorted((PROJECT_ROOT / "examples").glob("*.md"))
MONEY = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?")
CALL = re.compile(r"<summary>🔧 <code>(\w+)\((.*)\)</code></summary>")


def amounts(text: str) -> set[Decimal]:
    return {Decimal(f"{whole.replace('.', '')}.{cents or '00'}") for whole, cents in MONEY.findall(text)}


def parse_args(raw: str) -> dict:
    """Parse 'a=1, b="x", items=[{...}]' as written by run_examples.render."""
    args, pos, decoder = {}, 0, json.JSONDecoder()
    while pos < len(raw):
        match = re.compile(r"\s*(\w+)=").match(raw, pos)
        assert match, f"cannot parse arguments: {raw!r}"
        value, end = decoder.raw_decode(raw, match.end())
        args[match.group(1)] = value
        pos = end + 2 if raw.startswith(", ", end) else end
    return args


def parse_example(path: Path):
    text = path.read_text(encoding="utf-8")
    reference = re.search(r"\| Reference date \(`STORE_TODAY`\) \| (\S+)", text).group(1)
    events = []  # ("customer", text) | ("tool", name, args, result) | ("store", text)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("**Cliente:** "):
            events.append(("customer", line[len("**Cliente:** "):]))
        elif (m := CALL.match(line)):
            start = lines.index("```json", i) + 1
            end = lines.index("```", start)
            events.append(("tool", m.group(1), parse_args(m.group(2)), json.loads("\n".join(lines[start:end]))))
            i = end
        elif line.startswith("**Loja:** "):
            body = [line[len("**Loja:** "):]]
            while i + 1 < len(lines) and not lines[i + 1].startswith(("**Cliente:**", "<details>")):
                i += 1
                body.append(lines[i])
            events.append(("store", "\n".join(body)))
        i += 1
    return datetime.fromisoformat(reference).replace(tzinfo=STORE_TZ), events


def test_there_are_three_to_five_examples():
    assert 3 <= len(EXAMPLES) <= 5


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_recorded_tool_results_are_reproduced_by_current_code(path, db, tmp_path):
    now, events = parse_example(path)
    tools = StoreTools(db, now=lambda: now, handoffs_file=tmp_path / "handoffs.jsonl")
    calls = [e for e in events if e[0] == "tool"]
    for _, name, args, recorded in calls:
        assert tools.call(name, args) == recorded, f"{path.name}: {name}({args}) changed"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_amount_the_store_states_comes_from_a_tool_or_the_customer(path):
    _, events = parse_example(path)
    known: set[Decimal] = set()
    for event in events:
        if event[0] == "customer":
            known |= amounts(event[1])
        elif event[0] == "tool":
            known |= amounts(json.dumps(event[3], ensure_ascii=False))
            known |= {Decimal(str(v)).quantize(Decimal("0.01")) for v in event[2].values()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)}
        else:
            unexplained = amounts(event[1]) - known
            assert not unexplained, f"{path.name}: amounts not returned by any tool: {sorted(unexplained)}"
