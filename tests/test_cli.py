from emporio_agent.agent import ToolCall
from emporio_agent.cli import describe_tool_call, main


def test_describe_tool_call_is_compact_and_keeps_accents():
    call = ToolCall("get_product", {"product": "Violão Takamine"}, {"match": "none", "message": "x" * 1000})
    text = describe_tool_call(call, max_result_chars=80)
    assert text.startswith('get_product(product="Violão Takamine") -> {"match": "none"')
    assert text.endswith("...") and len(text) < 140


def test_cli_exits_with_message_when_key_is_missing(monkeypatch, capsys):
    monkeypatch.setattr("emporio_agent.cli.load_env", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert main([]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err
