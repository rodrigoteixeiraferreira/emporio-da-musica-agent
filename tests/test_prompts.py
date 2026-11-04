from datetime import datetime

from emporio_agent.config import STORE_TZ
from emporio_agent.prompts import build_system_prompt, store_status_line


def test_status_line_open_closed_and_holiday():
    assert "OPEN" in store_status_line(datetime(2026, 3, 25, 10, 0, tzinfo=STORE_TZ))
    closed = store_status_line(datetime(2026, 3, 28, 14, 0, tzinfo=STORE_TZ))
    assert "CLOSED" in closed and "segunda-feira, 30/03/2026 at 09:00" in closed
    assert "Sexta-feira Santa" in store_status_line(datetime(2026, 4, 3, 10, 0, tzinfo=STORE_TZ))


def test_prompt_has_rules_resolved_facts_and_the_whole_manual():
    prompt = build_system_prompt(datetime(2026, 3, 25, 10, 0, tzinfo=STORE_TZ))
    assert "quarta-feira, 25/03/2026 10:00" in prompt
    assert "(67) 3321-4500" in prompt and "contato@emporiodamusica.com.br" in prompt
    assert "### 4.1 Direito de Arrependimento" in prompt and "## 10. Disposições Finais" in prompt
