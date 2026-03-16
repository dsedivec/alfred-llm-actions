"""Tests for the minimal YAML parser, scalar formatter, and YAML writer."""

from llm import parse_yaml, write_yaml_value, yaml_scalar_str

# ---------------------------------------------------------------------------
# parse_yaml — scalar types
# ---------------------------------------------------------------------------


class TestParseYamlScalars:
    def test_string(self):
        assert parse_yaml("key: hello") == {"key": "hello"}

    def test_quoted_string_double(self):
        assert parse_yaml('key: "hello world"') == {"key": "hello world"}

    def test_quoted_string_single(self):
        assert parse_yaml("key: 'hello world'") == {"key": "hello world"}

    def test_int(self):
        assert parse_yaml("key: 42") == {"key": 42}

    def test_negative_int(self):
        assert parse_yaml("key: -7") == {"key": -7}

    def test_float(self):
        assert parse_yaml("key: 3.14") == {"key": 3.14}

    def test_bool_true(self):
        assert parse_yaml("key: true") == {"key": True}

    def test_bool_yes(self):
        assert parse_yaml("key: yes") == {"key": True}

    def test_bool_false(self):
        assert parse_yaml("key: false") == {"key": False}

    def test_bool_no(self):
        assert parse_yaml("key: no") == {"key": False}

    def test_null_word(self):
        assert parse_yaml("key: null") == {"key": None}

    def test_null_tilde(self):
        assert parse_yaml("key: ~") == {"key": None}

    def test_key_no_value(self):
        # "key:" with nothing after → nested block with no children → None
        assert parse_yaml("key:") == {"key": None}


# ---------------------------------------------------------------------------
# parse_yaml — structures
# ---------------------------------------------------------------------------


class TestParseYamlStructures:
    def test_nested_mapping(self):
        yaml = "a:\n  b: 1\n  c: 2"
        assert parse_yaml(yaml) == {"a": {"b": 1, "c": 2}}

    def test_list_of_scalars(self):
        yaml = "items:\n  - one\n  - two\n  - three"
        assert parse_yaml(yaml) == {"items": ["one", "two", "three"]}

    def test_list_of_mappings(self):
        yaml = "models:\n  - label: GPT-4\n    provider: openai\n  - label: Claude\n    provider: anthropic"
        result = parse_yaml(yaml)
        assert result == {
            "models": [
                {"label": "GPT-4", "provider": "openai"},
                {"label": "Claude", "provider": "anthropic"},
            ]
        }

    def test_flow_sequence(self):
        yaml = "tags: [alpha, beta, gamma]"
        assert parse_yaml(yaml) == {"tags": ["alpha", "beta", "gamma"]}

    def test_deeply_nested(self):
        yaml = "a:\n  b:\n    c:\n      d: deep"
        assert parse_yaml(yaml) == {"a": {"b": {"c": {"d": "deep"}}}}

    def test_list_item_with_nested_params(self):
        yaml = (
            "models:\n"
            "  - label: test\n"
            "    provider: openai\n"
            "    model: gpt-4\n"
            "    params:\n"
            "      temperature: 0.7\n"
            "      reasoning: high"
        )
        result = parse_yaml(yaml)
        assert result["models"][0]["params"] == {
            "temperature": 0.7,
            "reasoning": "high",
        }


# ---------------------------------------------------------------------------
# parse_yaml — comments and edge cases
# ---------------------------------------------------------------------------


class TestParseYamlEdgeCases:
    def test_line_comments_ignored(self):
        yaml = "# comment\nkey: value\n# another comment"
        assert parse_yaml(yaml) == {"key": "value"}

    def test_inline_comment(self):
        yaml = "key: value  # inline comment"
        assert parse_yaml(yaml) == {"key": "value"}

    def test_hash_in_quoted_string(self):
        yaml = 'key: "has # hash"'
        assert parse_yaml(yaml) == {"key": "has # hash"}

    def test_empty_input(self):
        assert parse_yaml("") == {}

    def test_blank_lines(self):
        yaml = "a: 1\n\n\nb: 2"
        assert parse_yaml(yaml) == {"a": 1, "b": 2}

    def test_multiple_top_level_keys(self):
        yaml = "x: 10\ny: 20\nz: 30"
        assert parse_yaml(yaml) == {"x": 10, "y": 20, "z": 30}


# ---------------------------------------------------------------------------
# yaml_scalar_str
# ---------------------------------------------------------------------------


class TestYamlScalarStr:
    def test_bool_true(self):
        assert yaml_scalar_str(True) == "true"

    def test_bool_false(self):
        assert yaml_scalar_str(False) == "false"

    def test_int(self):
        assert yaml_scalar_str(42) == "42"

    def test_float(self):
        assert yaml_scalar_str(3.14) == "3.14"

    def test_none(self):
        assert yaml_scalar_str(None) == "null"

    def test_plain_string(self):
        assert yaml_scalar_str("hello") == "hello"

    def test_string_with_colon(self):
        assert yaml_scalar_str("key: val") == '"key: val"'

    def test_string_with_hash(self):
        assert yaml_scalar_str("has # hash") == '"has # hash"'

    def test_string_with_brace(self):
        assert yaml_scalar_str("{value}") == '"{value}"'

    def test_string_with_bracket(self):
        assert yaml_scalar_str("[value]") == '"[value]"'

    def test_string_with_star(self):
        assert yaml_scalar_str("GPT-*") == '"GPT-*"'

    def test_string_with_question(self):
        assert yaml_scalar_str("what?") == '"what?"'


# ---------------------------------------------------------------------------
# write_yaml_value
# ---------------------------------------------------------------------------


class TestWriteYamlValue:
    def test_simple_scalar(self):
        lines = []
        write_yaml_value(lines, "key", "value", 0)
        assert lines == ["key: value"]

    def test_nested_dict(self):
        lines = []
        write_yaml_value(lines, "params", {"temperature": 0.7, "top_p": 0.9}, 0)
        assert lines == ["params:", "  temperature: 0.7", "  top_p: 0.9"]

    def test_list_of_scalars(self):
        lines = []
        write_yaml_value(lines, "tags", ["a", "b", "c"], 0)
        assert lines == ["tags:", "  - a", "  - b", "  - c"]

    def test_list_of_dicts(self):
        lines = []
        write_yaml_value(lines, "models", [{"label": "GPT", "provider": "openai"}], 0)
        assert lines[0] == "models:"
        assert lines[1] == "  - label: GPT"
        assert lines[2] == "    provider: openai"

    def test_indented(self):
        lines = []
        write_yaml_value(lines, "key", "val", 2)
        assert lines == ["    key: val"]
