#!/usr/bin/env python3
"""
Alfred Script Filter — Model selection list.
Outputs Alfred JSON for the llm-model keyword.
"""

import json
import os
import sys

# Import shared state from llm.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm import load_models, get_active_model

def main():
    query = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    active = get_active_model()

    items = []
    for entry in load_models():
        label = entry["label"]
        provider = entry["provider"]
        model_id = entry["model"]
        display = f"{provider}/{model_id} \u2014 {label}"
        if query and query not in display.lower() and query not in label.lower():
            continue
        is_active = label == active
        params_info = ""
        if entry.get("params"):
            keys = ", ".join(entry["params"].keys())
            params_info = f"  |  params: {keys}"
        items.append({
            "uid": label,
            "title": ("✓ " + label) if is_active else label,
            "subtitle": f"{provider}/{model_id}{params_info}"
                        + ("  [ACTIVE]" if is_active else ""),
            "arg": label,
            "icon": {"path": "icon.png"},
        })

    # Move active model to top
    items.sort(key=lambda x: (0 if "\u2713" in x["title"] else 1, x["title"]))

    print(json.dumps({"items": items}))


if __name__ == "__main__":
    main()
