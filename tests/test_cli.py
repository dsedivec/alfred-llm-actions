"""Tests for main() CLI dispatcher."""

import json
import sys
import pytest
import llm


@pytest.fixture(autouse=True)
def mock_notify(monkeypatch):
    """Mock notify() to avoid osascript calls on Linux."""
    calls = []
    monkeypatch.setattr(llm, "notify", lambda title, msg: calls.append((title, msg)))
    return calls


DEFAULTS = """\
models:
  - label: Test-Model
    provider: openai
    model: gpt-4o
  - label: Alt-Model
    provider: anthropic
    model: claude-sonnet-4-6
"""


def test_list_templates(write_default_models, model_dirs, monkeypatch, capsys):
    write_default_models(DEFAULTS)
    monkeypatch.setattr(sys, "argv", ["llm.py", "list-templates", ""])
    llm.main()
    output = json.loads(capsys.readouterr().out)
    assert "items" in output


def test_list_providers(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["llm.py", "list-providers", ""])
    llm.main()
    output = json.loads(capsys.readouterr().out)
    assert len(output["items"]) == 4


def test_set_model_valid(write_default_models, monkeypatch, mock_notify):
    write_default_models(DEFAULTS)
    monkeypatch.setattr(sys, "argv", ["llm.py", "set-model", "Test-Model"])
    llm.main()
    assert any("Test-Model" in msg for _, msg in mock_notify)


def test_set_model_invalid(write_default_models, monkeypatch, mock_notify):
    write_default_models(DEFAULTS)
    monkeypatch.setattr(sys, "argv", ["llm.py", "set-model", "Nonexistent"])
    llm.main()
    assert any("Unknown" in msg or "Error" in title for title, msg in mock_notify)


def test_unknown_command(monkeypatch, mock_notify):
    monkeypatch.setattr(sys, "argv", ["llm.py", "bogus-command"])
    llm.main()
    assert any("Unknown command" in msg for _, msg in mock_notify)


def test_no_args(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["llm.py"])
    llm.main()
    output = json.loads(capsys.readouterr().out)
    assert "items" in output
