"""The agent loop: Gemini native function calling, written out explicitly.

    user message -> model -> (tool calls -> tool results -> model)* -> text reply

The only Gemini-specific code in the project lives here, so swapping providers means
rewriting this module only (tools, prompts and rules are provider-agnostic).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google import genai
from google.genai import errors, types

from .config import gemini_model
from .prompts import build_system_prompt
from .tools import TOOL_DECLARATIONS, StoreTools

MAX_TOOL_ROUNDS = 6          # model turns per customer message before giving up
MAX_RETRIES = 5              # for 429 (per-minute limit) and 5xx
FALLBACK_REPLY = (
    "Desculpe, não consegui concluir a consulta agora. Você pode falar com a nossa equipe pelo "
    "WhatsApp (67) 3321-4500 ou pelo e-mail contato@emporiodamusica.com.br."
)


class DailyQuotaExceeded(RuntimeError):
    """The free tier's requests-per-day limit for this model is used up; retrying will not help."""


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    result: dict[str, Any]


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model_requests: int = 0


def _retry_delay_seconds(exc: errors.APIError, attempt: int) -> float:
    """Use the server's RetryInfo hint when present, else exponential backoff.

    429 (per-minute limit): 2, 4, 8, ... seconds. 5xx ("model overloaded" spikes last longer):
    5, 10, 20, 40, 60 seconds.
    """
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    if match:
        return float(match.group(1)) + 1
    if (exc.code or 0) >= 500:
        return float(min(60, 5 * 2**attempt))
    return float(2 ** (attempt + 1))


class Agent:
    def __init__(
        self,
        tools: StoreTools,
        client: Any | None = None,
        model: str | None = None,
        min_interval_s: float | None = None,
        on_tool_call: Callable[[ToolCall], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.tools = tools
        self.model = model or gemini_model()
        self.client = client or genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.min_interval_s = (
            float(os.getenv("GEMINI_MIN_INTERVAL_S", "0")) if min_interval_s is None else min_interval_s
        )
        self.on_tool_call = on_tool_call
        self.sleep = sleep
        self.total_requests = 0
        self._last_request_at = 0.0
        self.history: list[types.Content] = []
        self.config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(tools.now()),
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=d["name"], description=d["description"], parameters_json_schema=d["parameters"]
                )
                for d in TOOL_DECLARATIONS
            ])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def reset(self) -> None:
        """Forget the conversation (history is kept in memory only)."""
        self.history = []

    # ------------------------------------------------------------------ model call with retry

    def _generate(self) -> types.GenerateContentResponse:
        for attempt in range(MAX_RETRIES + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last_request_at)
            if wait > 0:
                self.sleep(wait)
            self._last_request_at = time.monotonic()
            try:
                self.total_requests += 1
                return self.client.models.generate_content(
                    model=self.model, contents=self.history, config=self.config
                )
            except errors.APIError as exc:
                if exc.code == 429 and "PerDay" in str(exc):
                    raise DailyQuotaExceeded(
                        f"Daily free-tier quota exhausted for {self.model}. Try another model, e.g. "
                        "GEMINI_MODEL=gemini-3.5-flash-lite, or wait for the reset (midnight Pacific time)."
                    ) from exc
                retryable = exc.code == 429 or (exc.code or 0) >= 500
                if not retryable or attempt == MAX_RETRIES:
                    raise
                self.sleep(_retry_delay_seconds(exc, attempt))
        raise AssertionError("unreachable")

    # ------------------------------------------------------------------ one customer message

    def send(self, user_text: str) -> Reply:
        checkpoint = len(self.history)
        try:
            return self._send(user_text)
        except Exception:
            del self.history[checkpoint:]  # a failed turn must not leave half a conversation behind
            raise

    def _send(self, user_text: str) -> Reply:
        reply = Reply(text="")
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._generate()
            reply.model_requests += 1
            candidate = response.candidates[0] if response.candidates else None
            content = candidate.content if candidate and candidate.content else None
            if content is None or not content.parts:
                break
            # Keep the model's turn untouched (it may carry thought signatures needed on the next call).
            self.history.append(content)

            calls = [p.function_call for p in content.parts if p.function_call]
            if not calls:
                reply.text = "".join(p.text for p in content.parts if p.text and not p.thought).strip()
                return reply

            results = []
            for call in calls:
                args = dict(call.args or {})
                result = self.tools.call(call.name, args)
                record = ToolCall(call.name, args, result)
                reply.tool_calls.append(record)
                if self.on_tool_call:
                    self.on_tool_call(record)
                results.append(types.Part(function_response=types.FunctionResponse(
                    id=call.id, name=call.name, response=result
                )))
            self.history.append(types.Content(role="user", parts=results))

        reply.text = FALLBACK_REPLY
        self.history.append(types.Content(role="model", parts=[types.Part(text=FALLBACK_REPLY)]))
        return reply
