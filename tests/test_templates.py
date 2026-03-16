"""Tests for parse_template and load_templates."""

import os

from llm import load_templates, parse_template


def test_full_frontmatter(model_dirs):
    _, _, templates_dir = model_dirs
    path = os.path.join(str(templates_dir), "summarize.txt")
    with open(path, "w") as f:
        f.write(
            "---\nname: Summarize\noutput: paste\nsystem: Be concise\n---\nSummarize: {{input}}\n"
        )
    t = parse_template(path)
    assert t["name"] == "Summarize"
    assert t["output"] == "paste"
    assert t["system"] == "Be concise"
    assert t["body"] == "Summarize: {{input}}"


def test_no_frontmatter(model_dirs):
    _, _, templates_dir = model_dirs
    path = os.path.join(str(templates_dir), "quick_fix.txt")
    with open(path, "w") as f:
        f.write("Fix this: {{input}}")
    t = parse_template(path)
    assert t["name"] == "quick_fix"
    assert t["output"] == "clipboard"
    assert t["system"] == ""
    assert t["body"] == "Fix this: {{input}}"


def test_empty_system(model_dirs):
    _, _, templates_dir = model_dirs
    path = os.path.join(str(templates_dir), "test.txt")
    with open(path, "w") as f:
        f.write("---\nname: Test\noutput: clipboard\nsystem:\n---\nHello {{input}}\n")
    t = parse_template(path)
    assert t["system"] == ""


def test_load_templates_sorted(model_dirs):
    _, _, templates_dir = model_dirs
    for name in ["zebra.txt", "alpha.txt", "middle.txt"]:
        with open(os.path.join(str(templates_dir), name), "w") as f:
            f.write(f"---\nname: {name[:-4]}\n---\nBody\n")
    templates = load_templates()
    names = [t["name"] for t in templates]
    assert names == ["alpha", "middle", "zebra"]


def test_non_txt_ignored(model_dirs):
    _, _, templates_dir = model_dirs
    with open(os.path.join(str(templates_dir), "valid.txt"), "w") as f:
        f.write("Body")
    with open(os.path.join(str(templates_dir), "ignored.md"), "w") as f:
        f.write("Body")
    with open(os.path.join(str(templates_dir), "ignored.yaml"), "w") as f:
        f.write("Body")
    templates = load_templates()
    assert len(templates) == 1
    assert templates[0]["name"] == "valid"


def test_empty_directory(model_dirs):
    templates = load_templates()
    assert templates == []
