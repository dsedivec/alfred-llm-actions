"""Shared fixtures for llm.py test suite."""

import os
import sys
import pytest

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm


@pytest.fixture(autouse=True)
def reset_models_cache():
    """Reset the global models cache before and after each test."""
    llm._models_cache = None
    yield
    llm._models_cache = None


@pytest.fixture
def model_dirs(tmp_path, monkeypatch):
    """Patch all path constants to point at tmp_path. Returns (tmp_path, state_dir, templates_dir)."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    monkeypatch.setattr(llm, "WORKFLOW_DIR", str(tmp_path))
    monkeypatch.setattr(llm, "TEMPLATES_DIR", str(templates_dir))
    monkeypatch.setattr(llm, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(llm, "SYSTEM_PROMPT_FILE", str(tmp_path / "system_prompt.txt"))
    monkeypatch.setattr(llm, "MODELS_DEFAULT_FILE", str(tmp_path / "models_default.yaml"))
    monkeypatch.setattr(llm, "MODELS_USER_FILE", str(tmp_path / "models.yaml"))
    monkeypatch.setattr(llm, "STATE_FILE", str(state_dir / "active_model.json"))
    monkeypatch.setattr(llm, "CONVERSATION_FILE", str(state_dir / "last_conversation.json"))

    return tmp_path, state_dir, templates_dir


@pytest.fixture
def write_default_models(model_dirs):
    """Return a helper that writes models_default.yaml content."""
    tmp_path = model_dirs[0]

    def _write(content):
        (tmp_path / "models_default.yaml").write_text(content)

    return _write


@pytest.fixture
def write_user_models(model_dirs):
    """Return a helper that writes models.yaml content."""
    tmp_path = model_dirs[0]

    def _write(content):
        (tmp_path / "models.yaml").write_text(content)

    return _write
