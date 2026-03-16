"""Tests for translate_shorthands."""

from llm import translate_shorthands

# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------


class TestReasoning:
    def test_anthropic_auto(self):
        result = translate_shorthands("anthropic", {"reasoning": "auto"})
        assert result["thinking"] == {"type": "enabled", "budget_tokens": 0}
        assert "reasoning" not in result

    def test_anthropic_high(self):
        result = translate_shorthands("anthropic", {"reasoning": "high"})
        assert result["thinking"]["budget_tokens"] == 10000

    def test_anthropic_medium(self):
        result = translate_shorthands("anthropic", {"reasoning": "medium"})
        assert result["thinking"]["budget_tokens"] == 5000

    def test_anthropic_low(self):
        result = translate_shorthands("anthropic", {"reasoning": "low"})
        assert result["thinking"]["budget_tokens"] == 2000

    def test_openai_auto(self):
        result = translate_shorthands("openai", {"reasoning": "auto"})
        assert result["reasoning_effort"] == "high"

    def test_openai_medium(self):
        result = translate_shorthands("openai", {"reasoning": "medium"})
        assert result["reasoning_effort"] == "medium"

    def test_openrouter_auto(self):
        result = translate_shorthands("openrouter", {"reasoning": "auto"})
        assert result["reasoning_effort"] == "high"

    def test_openrouter_low(self):
        result = translate_shorthands("openrouter", {"reasoning": "low"})
        assert result["reasoning_effort"] == "low"

    def test_gemini_auto(self):
        result = translate_shorthands("gemini", {"reasoning": "auto"})
        assert result["thinking_config"] == {"thinking_budget": -1}

    def test_gemini_high(self):
        result = translate_shorthands("gemini", {"reasoning": "high"})
        assert result["thinking_config"]["thinking_budget"] == 10000

    def test_gemini_medium(self):
        result = translate_shorthands("gemini", {"reasoning": "medium"})
        assert result["thinking_config"]["thinking_budget"] == 5000


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------


class TestWebSearch:
    def test_openai(self):
        result = translate_shorthands("openai", {"web_search": True})
        assert result["web_search_options"] == {"search_context_size": "medium"}
        assert "web_search" not in result

    def test_anthropic(self):
        result = translate_shorthands("anthropic", {"web_search": True})
        assert {"type": "web_search_20250305"} in result["tools"]

    def test_gemini(self):
        result = translate_shorthands("gemini", {"web_search": True})
        assert {"google_search": {}} in result["tools"]

    def test_openrouter(self):
        result = translate_shorthands("openrouter", {"web_search": True})
        assert "web" in result["plugins"]

    def test_false_is_noop(self):
        result = translate_shorthands("openai", {"web_search": False})
        assert "web_search_options" not in result
        assert "web_search" not in result


# ---------------------------------------------------------------------------
# Combined and edge cases
# ---------------------------------------------------------------------------


class TestCombined:
    def test_reasoning_and_web_search(self):
        result = translate_shorthands(
            "anthropic", {"reasoning": "high", "web_search": True}
        )
        assert result["thinking"]["budget_tokens"] == 10000
        assert {"type": "web_search_20250305"} in result["tools"]
        assert "reasoning" not in result
        assert "web_search" not in result

    def test_raw_params_passthrough(self):
        result = translate_shorthands("openai", {"temperature": 0.5})
        assert result["temperature"] == 0.5

    def test_raw_params_override_translated(self):
        # If user provides explicit reasoning_effort, it should win over shorthand
        result = translate_shorthands(
            "openai", {"reasoning": "auto", "reasoning_effort": "low"}
        )
        assert result["reasoning_effort"] == "low"

    def test_shorthand_keys_removed(self):
        result = translate_shorthands(
            "openai", {"reasoning": "auto", "web_search": True, "temperature": 0.5}
        )
        assert "reasoning" not in result
        assert "web_search" not in result

    def test_no_shorthands(self):
        result = translate_shorthands("openai", {"temperature": 0.7, "top_p": 0.9})
        assert result == {"temperature": 0.7, "top_p": 0.9}
