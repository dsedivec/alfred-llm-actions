"""Tests for load_models (model config loading and merging)."""

from llm import load_models

DEFAULTS_TWO_MODELS = """\
models:
  - label: GPT-4o
    provider: openai
    model: gpt-4o
  - label: Claude Sonnet
    provider: anthropic
    model: claude-sonnet-4-6
"""

DEFAULTS_MANY = """\
models:
  - label: GPT-4o
    provider: openai
    model: gpt-4o
  - label: GPT-4o-mini
    provider: openai
    model: gpt-4o-mini
  - label: Claude Sonnet
    provider: anthropic
    model: claude-sonnet-4-6
  - label: Gemini Pro
    provider: gemini
    model: gemini-pro
"""


def test_defaults_only(write_default_models):
    write_default_models(DEFAULTS_TWO_MODELS)
    models = load_models()
    assert len(models) == 2
    assert models[0]["label"] == "GPT-4o"
    assert models[1]["label"] == "Claude Sonnet"


def test_user_additions(write_default_models, write_user_models):
    write_default_models(DEFAULTS_TWO_MODELS)
    write_user_models(
        "models:\n"
        "  - label: Custom\n"
        "    provider: openrouter\n"
        "    model: my-model\n"
    )
    models = load_models()
    assert len(models) == 3
    assert models[2]["label"] == "Custom"


def test_remove_exact_match(write_default_models, write_user_models):
    write_default_models(DEFAULTS_TWO_MODELS)
    write_user_models("models:\n  - remove_defaults: GPT-4o\n")
    models = load_models()
    assert len(models) == 1
    assert models[0]["label"] == "Claude Sonnet"


def test_remove_glob(write_default_models, write_user_models):
    write_default_models(DEFAULTS_MANY)
    write_user_models('models:\n  - remove_defaults: "GPT-*"\n')
    models = load_models()
    labels = [m["label"] for m in models]
    assert "GPT-4o" not in labels
    assert "GPT-4o-mini" not in labels
    assert "Claude Sonnet" in labels
    assert "Gemini Pro" in labels


def test_remove_and_add(write_default_models, write_user_models):
    write_default_models(DEFAULTS_TWO_MODELS)
    write_user_models(
        "models:\n"
        "  - remove_defaults: GPT-4o\n"
        "  - label: Replacement\n"
        "    provider: openai\n"
        "    model: gpt-4-turbo\n"
    )
    models = load_models()
    labels = [m["label"] for m in models]
    assert "GPT-4o" not in labels
    assert "Replacement" in labels
    assert "Claude Sonnet" in labels


def test_model_with_params(write_default_models):
    write_default_models(
        "models:\n"
        "  - label: Test\n"
        "    provider: openai\n"
        "    model: gpt-4o\n"
        "    params:\n"
        "      temperature: 0.5\n"
        "      reasoning: high\n"
    )
    models = load_models()
    assert models[0]["params"]["temperature"] == 0.5
    assert models[0]["params"]["reasoning"] == "high"


def test_remove_alias(write_default_models, write_user_models):
    """'remove' should work the same as 'remove_defaults'."""
    write_default_models(DEFAULTS_TWO_MODELS)
    write_user_models("models:\n  - remove: GPT-4o\n")
    models = load_models()
    assert len(models) == 1
    assert models[0]["label"] == "Claude Sonnet"


def test_no_user_file(write_default_models):
    """When models.yaml doesn't exist, defaults are returned as-is."""
    write_default_models(DEFAULTS_TWO_MODELS)
    models = load_models()
    assert len(models) == 2
