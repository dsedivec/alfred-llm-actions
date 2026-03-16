"""Tests for state management: active model and conversation persistence."""

from llm import get_active_model, load_conversation, save_conversation, set_active_model

DEFAULTS = """\
models:
  - label: Model-A
    provider: openai
    model: gpt-4o
  - label: Model-B
    provider: anthropic
    model: claude-sonnet-4-6
"""


def test_default_first_model(write_default_models):
    write_default_models(DEFAULTS)
    assert get_active_model() == "Model-A"


def test_set_get_roundtrip(write_default_models):
    write_default_models(DEFAULTS)
    set_active_model("Model-B")
    assert get_active_model() == "Model-B"


def test_invalid_stored_falls_back(write_default_models):
    write_default_models(DEFAULTS)
    set_active_model("Nonexistent")
    assert get_active_model() == "Model-A"


def test_conversation_roundtrip(model_dirs):
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    save_conversation(msgs, "test-model")
    loaded = load_conversation()
    assert loaded is not None
    assert loaded["model"] == "test-model"
    assert loaded["messages"] == msgs


def test_conversation_no_file(model_dirs):
    assert load_conversation() is None
