"""Tests for API call functions with mocked HTTP."""

import pytest

from llm import call_anthropic, call_gemini, call_openai_compatible


class _MockHttpPost:
    def __init__(self):
        self.calls = []
        self._response = {}

    def __call__(self, url, headers, payload, timeout=60):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        return self._response


@pytest.fixture
def mock_http_post(monkeypatch):
    """Mock _http_post and return a callable that sets the response."""
    mock = _MockHttpPost()

    import llm

    monkeypatch.setattr(llm, "_http_post", mock)
    return mock


class TestCallOpenAICompatible:
    def test_payload_structure(self, mock_http_post):
        mock_http_post._response = {"choices": [{"message": {"content": "Hi!"}}]}
        result = call_openai_compatible(
            "https://api.openai.com/v1/chat/completions",
            "sk-test",
            "gpt-4o",
            "Be helpful",
            [{"role": "user", "content": "Hello"}],
        )
        assert result == "Hi!"
        payload = mock_http_post.calls[0]["payload"]
        assert payload["model"] == "gpt-4o"
        assert payload["messages"][0] == {"role": "system", "content": "Be helpful"}
        assert payload["messages"][1] == {"role": "user", "content": "Hello"}

    def test_no_system_prompt(self, mock_http_post):
        mock_http_post._response = {"choices": [{"message": {"content": "Hi!"}}]}
        call_openai_compatible(
            "https://api.openai.com/v1/chat/completions",
            "sk-test",
            "gpt-4o",
            "",
            [{"role": "user", "content": "Hello"}],
        )
        payload = mock_http_post.calls[0]["payload"]
        # No system message when system_prompt is empty
        assert payload["messages"][0]["role"] == "user"

    def test_params_merged(self, mock_http_post):
        mock_http_post._response = {"choices": [{"message": {"content": "ok"}}]}
        call_openai_compatible(
            "https://api.openai.com/v1/chat/completions",
            "sk-test",
            "gpt-4o",
            "",
            [{"role": "user", "content": "Hi"}],
            params={"temperature": 0.5},
        )
        payload = mock_http_post.calls[0]["payload"]
        assert payload["temperature"] == 0.5
        # Messages not overwritten by merge
        assert len(payload["messages"]) == 1

    def test_messages_preserved_with_params(self, mock_http_post):
        mock_http_post._response = {"choices": [{"message": {"content": "ok"}}]}
        call_openai_compatible(
            "https://api.openai.com/v1/chat/completions",
            "sk-test",
            "gpt-4o",
            "sys",
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ],
            params={"temperature": 0.7},
        )
        payload = mock_http_post.calls[0]["payload"]
        assert len(payload["messages"]) == 4  # system + 3 conversation


class TestCallAnthropic:
    def test_basic_response(self, mock_http_post):
        mock_http_post._response = {"content": [{"type": "text", "text": "Hello!"}]}
        result = call_anthropic(
            "sk-test",
            "claude-sonnet-4-6",
            "Be helpful",
            [{"role": "user", "content": "Hi"}],
        )
        assert result == "Hello!"
        payload = mock_http_post.calls[0]["payload"]
        assert payload["model"] == "claude-sonnet-4-6"
        assert payload["system"] == "Be helpful"

    def test_thinking_bumps_max_tokens(self, mock_http_post):
        mock_http_post._response = {"content": [{"type": "text", "text": "ok"}]}
        call_anthropic(
            "sk-test",
            "claude-sonnet-4-6",
            "",
            [{"role": "user", "content": "Hi"}],
            params={"thinking": {"type": "enabled", "budget_tokens": 10000}},
        )
        payload = mock_http_post.calls[0]["payload"]
        assert payload["max_tokens"] >= 10000 + 4096

    def test_multi_block_extracts_text(self, mock_http_post):
        mock_http_post._response = {
            "content": [
                {"type": "thinking", "text": "Let me think..."},
                {"type": "text", "text": "The answer is 42."},
            ]
        }
        result = call_anthropic(
            "sk-test",
            "claude-sonnet-4-6",
            "",
            [{"role": "user", "content": "What is the meaning of life?"}],
        )
        assert result == "The answer is 42."


class TestCallGemini:
    def test_message_role_mapping(self, mock_http_post):
        mock_http_post._response = {
            "candidates": [{"content": {"parts": [{"text": "Hi!"}]}}]
        }
        call_gemini(
            "key-test",
            "gemini-pro",
            "",
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "How are you?"},
            ],
        )
        payload = mock_http_post.calls[0]["payload"]
        roles = [c["role"] for c in payload["contents"]]
        assert roles == ["user", "model", "user"]

    def test_system_instruction(self, mock_http_post):
        mock_http_post._response = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        }
        call_gemini(
            "key-test",
            "gemini-pro",
            "Be concise",
            [{"role": "user", "content": "Hi"}],
        )
        payload = mock_http_post.calls[0]["payload"]
        assert payload["systemInstruction"] == {"parts": [{"text": "Be concise"}]}

    def test_response_extraction(self, mock_http_post):
        mock_http_post._response = {
            "candidates": [{"content": {"parts": [{"text": "Result"}]}}]
        }
        result = call_gemini(
            "key-test",
            "gemini-pro",
            "",
            [{"role": "user", "content": "Hi"}],
        )
        assert result == "Result"
