"""The example writer, with a fake reply (no network)."""

import importlib.util

from emporio_agent.agent import Reply, ToolCall
from emporio_agent.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("run_examples", PROJECT_ROOT / "scripts" / "run_examples.py")
run_examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_examples)


def test_scenarios_cover_the_brief():
    assert [s["id"] for s in run_examples.SCENARIOS] == [1, 2, 3, 4, 5]
    assert all(s["messages"] for s in run_examples.SCENARIOS)


def test_render_has_header_tool_calls_and_turns():
    reply = Reply(text="Custa R$ 2.199,00.\nAlgo mais?",
                  tool_calls=[ToolCall("get_product", {"product": "Takamine GD20"}, {"final_price": "R$ 2.199,00"})])
    md = run_examples.render(run_examples.SCENARIOS[1], "gemini-test", [("Quanto custa?", reply)], requests=2)
    assert md.startswith("# Example 2 — ")
    for needle in ["| Model | `gemini-test`", "| Reference date (`STORE_TODAY`) | 2026-03-25T10:00",
                   "| Commit |", "| Model requests | 2 |", "**Cliente:** Quanto custa?",
                   'get_product(product="Takamine GD20")', '"final_price": "R$ 2.199,00"',
                   "**Loja:** Custa R$ 2.199,00.  \nAlgo mais?"]:
        assert needle in md
