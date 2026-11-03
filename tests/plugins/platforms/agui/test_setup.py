"""``hermes gateway setup`` writes the AG-UI listener without disturbing other settings."""

import pytest

from hermes_cli import setup as setup_mod
from hermes_cli.config import get_env_value, load_config, save_config

HOST_QUESTION = "Bind host (127.0.0.1 = local only; 0.0.0.0 = network)"
PORT_QUESTION = "Port (0 = OS-assigned)"
TOKEN_QUESTION = "Session token (blank = generate a strong one)"


def _answer_prompts(monkeypatch, replies):
    """Route ``setup.prompt`` by exact question and record the defaults offered."""
    seen = {}

    def fake_prompt(question, default=None, password=False):
        seen[question] = default
        return replies.get(question, default or "")

    monkeypatch.setattr(setup_mod, "prompt", fake_prompt)
    return seen


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
@pytest.mark.parametrize("port_input,expected_port", [("9123", 9123), (float("inf"), 8000)])
def test_setup_persists_listener_preserves_section_and_separates_secret(
    monkeypatch, host, port_input, expected_port
):
    from plugins.platforms.agui import interactive_setup

    save_config(
        {
            "platforms": {
                "agui": {
                    "frontend_tool_timeout": 17,
                    "conversation_idle_timeout": 31,
                    "max_conversations": 2,
                    "future_setting": "preserved",
                    "port": float("inf"),
                    "provider": "custom",
                    "model": "old-model",
                    "api_mode": "chat_completions",
                    "base_url": "http://localhost:4010/v1",
                }
            }
        }
    )
    fake_token = "a7G4p2N9s5T1u8V6c3D0f9H2j4K7m1Q5"
    _answer_prompts(
        monkeypatch,
        {HOST_QUESTION: host, PORT_QUESTION: port_input, TOKEN_QUESTION: fake_token},
    )
    monkeypatch.setattr(
        setup_mod,
        "prompt_yes_no",
        lambda question, default=True, description=None: host == "0.0.0.0",
    )

    interactive_setup()

    saved = load_config()["platforms"]["agui"]
    assert (saved["host"], saved["port"]) == (host, expected_port)
    assert saved["enabled"] is True
    assert (
        saved["frontend_tool_timeout"],
        saved["conversation_idle_timeout"],
        saved["max_conversations"],
    ) == (17, 31, 2)
    assert saved["future_setting"] == "preserved"
    assert (
        saved["provider"],
        saved["model"],
        saved["api_mode"],
        saved["base_url"],
    ) == ("custom", "old-model", "chat_completions", "http://localhost:4010/v1")
    assert fake_token not in str(saved)
    assert get_env_value("HERMES_AGUI_SESSION_TOKEN") == (
        fake_token if host == "0.0.0.0" else None
    )


def test_prompt_defaults_use_the_resolved_listener_not_the_raw_config(monkeypatch):
    """A hand-edited ``port: .inf`` must not raise while prompting for a new one."""
    from plugins.platforms.agui import interactive_setup

    # Legacy spelling: the prompt follows what the server would actually use.
    save_config({"agui": {"host": "0.0.0.0", "port": float("inf")}})
    seen = _answer_prompts(monkeypatch, {})
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *args, **kwargs: False)

    interactive_setup()

    assert seen[HOST_QUESTION] == "0.0.0.0"
    assert seen[PORT_QUESTION] == "8000"
    saved = load_config()["platforms"]["agui"]
    assert (saved["host"], saved["port"]) == ("0.0.0.0", 8000)


@pytest.mark.parametrize(
    "host,default_answer", [("127.0.0.1", False), ("0.0.0.0", True)]
)
def test_token_question_default_follows_bind_reach(monkeypatch, host, default_answer):
    from plugins.platforms.agui import interactive_setup

    save_config({"platforms": {"agui": {}}})
    _answer_prompts(monkeypatch, {HOST_QUESTION: host})
    asked = {}

    def decline(question, default=True, description=None):
        asked["question"] = question
        asked["default"] = default
        return False

    monkeypatch.setattr(setup_mod, "prompt_yes_no", decline)
    warnings = []
    monkeypatch.setattr(setup_mod, "print_warning", warnings.append)

    interactive_setup()

    assert asked == {"question": "Set an AG-UI session token?", "default": default_answer}
    if host == "0.0.0.0":
        assert any("will be refused" in warning for warning in warnings)
    else:
        assert not any("will be refused" in warning for warning in warnings)
    assert get_env_value("HERMES_AGUI_SESSION_TOKEN") is None


def test_existing_token_offers_replacement_and_keeps_it_when_declined(monkeypatch):
    from hermes_cli.config import save_env_value
    from plugins.platforms.agui import interactive_setup

    save_config({"platforms": {"agui": {}}})
    existing = "existing-token-0123456789"
    save_env_value("HERMES_AGUI_SESSION_TOKEN", existing)
    _answer_prompts(monkeypatch, {HOST_QUESTION: "127.0.0.1"})
    questions = []

    def decline(question, default=True, description=None):
        questions.append((question, default))
        return False

    monkeypatch.setattr(setup_mod, "prompt_yes_no", decline)

    interactive_setup()

    assert questions == [("Replace the existing AG-UI session token?", False)]
    assert get_env_value("HERMES_AGUI_SESSION_TOKEN") == existing


def test_blank_token_generates_a_strong_secret(monkeypatch):
    from plugins.platforms.agui import interactive_setup

    save_config({"platforms": {"agui": {}}})
    _answer_prompts(
        monkeypatch,
        {HOST_QUESTION: "0.0.0.0", TOKEN_QUESTION: ""},
    )
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *args, **kwargs: True)
    printed = []
    monkeypatch.setattr(setup_mod, "print_info", printed.append)

    interactive_setup()

    token = get_env_value("HERMES_AGUI_SESSION_TOKEN")
    assert token is not None and len(token) >= 32
    assert any("Generated token" in text for text in printed)
