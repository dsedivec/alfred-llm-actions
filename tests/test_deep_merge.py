"""Tests for deep_merge."""

from llm import deep_merge


def test_flat_override():
    assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_flat_addition():
    assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_nested_recursive():
    base = {"a": {"x": 1, "y": 2}}
    override = {"a": {"y": 3, "z": 4}}
    assert deep_merge(base, override) == {"a": {"x": 1, "y": 3, "z": 4}}


def test_dict_overridden_by_scalar():
    assert deep_merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}


def test_scalar_overridden_by_dict():
    assert deep_merge({"a": 5}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_non_mutation():
    base = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    deep_merge(base, override)
    assert base == {"a": {"x": 1}}


def test_three_level_deep():
    base = {"a": {"b": {"c": 1, "d": 2}}}
    override = {"a": {"b": {"d": 3, "e": 4}}}
    assert deep_merge(base, override) == {"a": {"b": {"c": 1, "d": 3, "e": 4}}}


def test_empty_override():
    assert deep_merge({"a": 1}, {}) == {"a": 1}


def test_empty_base():
    assert deep_merge({}, {"a": 1}) == {"a": 1}
