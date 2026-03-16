"""Tests for Alfred script filter JSON output functions."""

import json

from llm import label_model_as_alfred_items, list_providers_as_alfred_items


class TestListProviders:
    def test_no_filter(self):
        result = json.loads(list_providers_as_alfred_items(""))
        assert len(result["items"]) == 4
        ids = [item["arg"] for item in result["items"]]
        assert set(ids) == {"openai", "anthropic", "gemini", "openrouter"}

    def test_filter_narrows(self):
        result = json.loads(list_providers_as_alfred_items("open"))
        ids = [item["arg"] for item in result["items"]]
        assert "openai" in ids
        assert "openrouter" in ids
        assert "anthropic" not in ids

    def test_no_match(self):
        result = json.loads(list_providers_as_alfred_items("zzzzz"))
        assert result["items"] == []


class TestLabelModel:
    def test_default_label(self):
        result = json.loads(label_model_as_alfred_items("openai:gpt-4o", ""))
        item = result["items"][0]
        assert item["title"] == "openai/gpt-4o"

    def test_custom_label(self):
        result = json.loads(label_model_as_alfred_items("openai:gpt-4o", "My GPT"))
        item = result["items"][0]
        assert item["title"] == "My GPT"
        assert item["arg"] == "My GPT"
