"""The agent loop with a scripted fake client (no network), plus one live smoke test."""

import os
from datetime import datetime

import pytest
from google.genai import errors, types

from emporio_agent.agent import FALLBACK_REPLY, Agent, DailyQuotaExceeded
from emporio_agent.config import STORE_TZ, load_env
from emporio_agent.tools import StoreTools

NOW = datetime(2026, 3, 25, 10, 0, tzinfo=STORE_TZ)


def call_response(name, args):
    part = types.Part(function_call=types.FunctionCall(id="c1", name=name, args=args))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])


def text_response(text):
    part = types.Part(text=text)
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])


class FakeModels:
    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def generate_content(self, model, contents, config):
        self.seen.append(list(contents))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


@pytest.fixture
def tools(db, tmp_path):
    return StoreTools(db, now=lambda: NOW, handoffs_file=tmp_path / "h.jsonl")


def make_agent(tools, script):
    return Agent(tools, client=FakeClient(script), model="fake", min_interval_s=0, sleep=lambda s: None)


def test_tool_call_round_trip(tools):
    agent = make_agent(tools, [call_response("get_product", {"product": "Takamine GD20"}), text_response("Custa R$ 2.199,00.")])
    reply = agent.send("Quanto custa o Takamine GD20?")
    assert reply.text == "Custa R$ 2.199,00."
    assert [c.name for c in reply.tool_calls] == ["get_product"]
    assert reply.tool_calls[0].result["pricing"]["final_price"] == "R$ 2.199,00"
    # The second model call received the tool result.
    second_call = agent.client.models.seen[1]
    response_part = second_call[-1].parts[0].function_response
    assert response_part.name == "get_product" and response_part.response["product_id"] == 95
    assert len(agent.history) == 4  # user, model(call), user(result), model(text)


def test_loop_stops_after_too_many_tool_rounds(tools):
    agent = make_agent(tools, [call_response("get_store_status", {})] * 10)
    reply = agent.send("?")
    assert reply.text == FALLBACK_REPLY and reply.model_requests == 6


def test_rate_limit_is_retried_with_backoff(tools):
    rate_limited = errors.APIError(429, {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}})
    sleeps = []
    agent = Agent(tools, client=FakeClient([rate_limited, rate_limited, text_response("Oi!")]), model="fake",
                  min_interval_s=0, sleep=sleeps.append)
    assert agent.send("oi").text == "Oi!"
    assert sleeps == [2.0, 4.0]


def test_daily_quota_fails_fast_and_rolls_back_history(tools):
    daily = errors.APIError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                            "message": "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})
    agent = make_agent(tools, [daily])
    with pytest.raises(DailyQuotaExceeded):
        agent.send("oi")
    assert agent.history == []


def test_reset_clears_history(tools):
    agent = make_agent(tools, [text_response("Olá!")])
    agent.send("oi")
    agent.reset()
    assert agent.history == []


load_env()


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
def test_live_price_question_calls_get_product(tools):
    # Uses a Flash-Lite model by default to spare the low daily quota of the Flash models.
    agent = Agent(tools, model=os.getenv("GEMINI_TEST_MODEL", "gemini-3.5-flash-lite"))
    reply = agent.send("Quanto custa o Takamine GD20?")
    assert "get_product" in [c.name for c in reply.tool_calls]
    assert "2.199" in reply.text
