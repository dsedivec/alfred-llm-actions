#!/usr/bin/env python3
"""
Alfred LLM Workflow — Main script
Handles API calls, template loading, state management, and output delivery.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

WORKFLOW_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(WORKFLOW_DIR, "templates")
SYSTEM_PROMPT_FILE = os.path.join(WORKFLOW_DIR, "system_prompt.txt")


def _resolve_data_dir():
    d = os.environ.get("alfred_workflow_data")
    if d:
        return d
    return os.path.join(WORKFLOW_DIR, "data")


# User-mutable (survives workflow updates)
DATA_DIR = _resolve_data_dir()
STATE_DIR = os.path.join(DATA_DIR, "state")

os.makedirs(STATE_DIR, exist_ok=True)


def _migrate_user_data():
    """Copy user files from WORKFLOW_DIR to DATA_DIR on first run after update."""
    # Skip if DATA_DIR is inside WORKFLOW_DIR (fallback mode)
    if DATA_DIR.startswith(WORKFLOW_DIR + os.sep) or DATA_DIR == WORKFLOW_DIR:
        return
    old_models = os.path.join(WORKFLOW_DIR, "models.yaml")
    if os.path.exists(old_models) and not os.path.exists(MODELS_USER_FILE):
        shutil.copy2(old_models, MODELS_USER_FILE)
    old_state = os.path.join(WORKFLOW_DIR, "state")
    if os.path.isdir(old_state):
        for fname in os.listdir(old_state):
            src = os.path.join(old_state, fname)
            dst = os.path.join(STATE_DIR, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)


_migrate_user_data()

# ---------------------------------------------------------------------------
# YAML parser (minimal subset — no PyYAML dependency)
# ---------------------------------------------------------------------------


def _parse_yaml(text):
    """Parse a minimal YAML subset: mappings, lists, scalars, comments."""

    def _scalar(s):
        s = s.strip()
        if not s:
            return ""
        if (s.startswith('"') and s.endswith('"')) or (
            s.startswith("'") and s.endswith("'")
        ):
            return s[1:-1]
        low = s.lower()
        if low in ("true", "yes"):
            return True
        if low in ("false", "no"):
            return False
        if low in ("null", "~"):
            return None
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s

    def _strip_comment(line):
        in_quote = None
        for i, ch in enumerate(line):
            if ch in ('"', "'") and not in_quote:
                in_quote = ch
            elif ch == in_quote:
                in_quote = None
            elif ch == "#" and not in_quote:
                return line[:i].rstrip()
        return line

    # Build (indent, content) list, skipping blanks/comments
    entries = []
    for raw in text.split("\n"):
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(stripped)
        content = _strip_comment(stripped)
        if content:
            entries.append((indent, content))

    def _collect(idx, min_indent):
        """Collect consecutive entries with indent >= min_indent. Returns (sub_entries, next_idx)."""
        sub = []
        while idx < len(entries) and entries[idx][0] >= min_indent:
            sub.append(entries[idx])
            idx += 1
        return sub, idx

    def _parse(lines):
        """Parse a list of (indent, content) tuples into a Python object."""
        if not lines:
            return None
        # Determine if this block is a list or mapping
        _, first = lines[0]
        if first.startswith("- "):
            return _parse_list(lines)
        elif ":" in first:
            return _parse_mapping(lines)
        else:
            return _scalar(first)

    def _parse_list(lines):
        result = []
        base = lines[0][0]
        i = 0
        while i < len(lines):
            indent, content = lines[i]
            if indent != base or not content.startswith("- "):
                i += 1
                continue
            item_text = content[2:].strip()
            # Gather child lines (indent > base) belonging to this list item
            children = []
            j = i + 1
            while j < len(lines) and lines[j][0] > base:
                children.append(lines[j])
                j += 1

            if ":" in item_text and not (
                item_text.startswith('"') or item_text.startswith("'")
            ):
                # "- key: value" starts a mapping item
                # Normalize: treat "- key: val" as a mapping line at indent base+2
                first_line = (base + 2, item_text)
                item = _parse_mapping([first_line] + children)
                result.append(item)
            elif item_text:
                result.append(_scalar(item_text))
            elif children:
                result.append(_parse(children))
            else:
                result.append(None)
            i = j
        return result

    def _parse_mapping(lines):
        result = {}
        base = lines[0][0]
        i = 0
        while i < len(lines):
            indent, content = lines[i]
            if indent != base:
                i += 1
                continue
            if ":" not in content:
                i += 1
                continue
            key, val_str = content.split(":", 1)
            key = key.strip()
            val_str = val_str.strip()
            if val_str:
                # Inline flow sequence: [item1, item2]
                if val_str.startswith("[") and val_str.endswith("]"):
                    inner = val_str[1:-1]
                    result[key] = [
                        _scalar(x.strip()) for x in inner.split(",") if x.strip()
                    ]
                else:
                    result[key] = _scalar(val_str)
                i += 1
            else:
                # Value is a nested block
                children = []
                j = i + 1
                while j < len(lines) and lines[j][0] > base:
                    children.append(lines[j])
                    j += 1
                result[key] = _parse(children)
                i = j
        return result

    if not entries:
        return {}
    result = _parse(entries)
    return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# Model loading from YAML
# ---------------------------------------------------------------------------

MODELS_DEFAULT_FILE = os.path.join(WORKFLOW_DIR, "models_default.yaml")
MODELS_USER_FILE = os.path.join(DATA_DIR, "models.yaml")

_models_cache = None


def _deep_merge(base, override):
    """Deep-merge override dict into base dict. Returns new dict."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_models():
    """Load and merge models from YAML config files. Returns list of model entries."""
    global _models_cache
    if _models_cache is not None:
        return _models_cache

    # Load defaults
    with open(MODELS_DEFAULT_FILE) as f:
        defaults = _parse_yaml(f.read())
    models = list(defaults.get("models", []))

    # Load user overrides
    if os.path.exists(MODELS_USER_FILE):
        with open(MODELS_USER_FILE) as f:
            user = _parse_yaml(f.read())
        removals = []
        additions = []
        for entry in user.get("models", []):
            if not isinstance(entry, dict):
                continue
            if "remove_defaults" in entry:
                removals.append(entry["remove_defaults"])
            elif "remove" in entry:
                removals.append(entry["remove"])
            elif "label" in entry:
                additions.append(entry)
        # Apply removals to defaults only
        for pattern in removals:
            models = [
                m
                for m in models
                if not fnmatch.fnmatchcase(m.get("label", ""), pattern)
            ]
        models.extend(additions)

    _models_cache = models
    return models


def get_models_dict():
    """Return {label: model_entry} mapping for lookup."""
    return {m["label"]: m for m in load_models()}


# ---------------------------------------------------------------------------
# Provider model cache (for llm-add browsing)
# ---------------------------------------------------------------------------

MODELS_CACHE_TTL = 3600


def _models_cache_path(provider):
    return os.path.join(STATE_DIR, f"models_cache_{provider}.json")


def _load_models_cache(provider):
    path = _models_cache_path(provider)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > MODELS_CACHE_TTL:
            return None
        return data.get("models", [])
    except (json.JSONDecodeError, KeyError):
        return None


def _save_models_cache(provider, models):
    with open(_models_cache_path(provider), "w") as f:
        json.dump({"timestamp": time.time(), "models": models}, f)


# Non-chat model prefixes to filter out from OpenAI listings
_OPENAI_SKIP_PREFIXES = (
    "dall-e",
    "whisper",
    "tts",
    "text-embedding",
    "embedding",
    "davinci",
    "babbage",
    "curie",
    "ada",
    "moderation",
    "text-search",
    "text-similarity",
    "code-search",
)


def _fetch_provider_models(provider):
    """Fetch available models for a provider. Returns list of {id, name} dicts."""
    cached = _load_models_cache(provider)
    if cached is not None:
        return cached

    models = []
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return []
        data = _http_get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        for m in data.get("data", []):
            mid = m.get("id", "")
            if any(mid.startswith(p) for p in _OPENAI_SKIP_PREFIXES):
                continue
            models.append({"id": mid, "name": mid})
        models.sort(key=lambda x: x["id"])

    elif provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return []
        data = _http_get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
        )
        for m in data.get("models", []):
            mid = m.get("name", "").removeprefix("models/")
            name = m.get("displayName", mid)
            models.append({"id": mid, "name": name})

    elif provider == "openrouter":
        data = _http_get("https://openrouter.ai/api/v1/models")
        for m in data.get("data", []):
            mid = m.get("id", "")
            name = m.get("name", mid)
            models.append({"id": mid, "name": name})
        models.sort(key=lambda x: x["name"])

    elif provider == "anthropic":
        return []  # Manual entry only

    if models:
        _save_models_cache(provider, models)
    return models


# ---------------------------------------------------------------------------
# YAML writer (for models.yaml)
# ---------------------------------------------------------------------------


def _yaml_scalar_str(value):
    """Format a Python value as a YAML scalar string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    s = str(value)
    if s and not any(
        c in s
        for c in (
            ":",
            "#",
            "{",
            "}",
            "[",
            "]",
            ",",
            "&",
            "*",
            "?",
            "|",
            "-",
            "<",
            ">",
            "=",
            "!",
            "%",
            "@",
            "`",
            '"',
            "'",
        )
    ):
        return s
    return f'"{s}"'


def _write_yaml_value(lines, key, value, indent):
    """Recursively write a YAML key-value pair."""
    prefix = "  " * indent
    if isinstance(value, dict):
        lines.append(f"{prefix}{key}:")
        for k, v in value.items():
            _write_yaml_value(lines, k, v, indent + 1)
    elif isinstance(value, list):
        lines.append(f"{prefix}{key}:")
        for item in value:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    if first:
                        if isinstance(v, (dict, list)):
                            lines.append(f"{prefix}  - {k}:")
                            if isinstance(v, dict):
                                for k2, v2 in v.items():
                                    _write_yaml_value(lines, k2, v2, indent + 3)
                            elif isinstance(v, list):
                                for li in v:
                                    lines.append(
                                        f"{prefix}      - {_yaml_scalar_str(li)}"
                                    )
                        else:
                            lines.append(f"{prefix}  - {k}: {_yaml_scalar_str(v)}")
                        first = False
                    else:
                        _write_yaml_value(lines, k, v, indent + 2)
            else:
                lines.append(f"{prefix}  - {_yaml_scalar_str(item)}")
    else:
        lines.append(f"{prefix}{key}: {_yaml_scalar_str(value)}")


def _load_user_models_raw():
    """Parse models.yaml, return (entries_list, removals_list) separately."""
    entries = []
    removals = []
    if not os.path.exists(MODELS_USER_FILE):
        return entries, removals
    with open(MODELS_USER_FILE) as f:
        data = _parse_yaml(f.read())
    for item in data.get("models", []):
        if not isinstance(item, dict):
            continue
        if "remove_defaults" in item:
            removals.append(item["remove_defaults"])
        elif "remove" in item:
            removals.append(item["remove"])
        else:
            entries.append(item)
    return entries, removals


def _save_user_models(entries, removals):
    """Write models.yaml from structured data."""
    lines = ["models:"]
    for pattern in removals:
        lines.append(f"  - remove_defaults: {_yaml_scalar_str(pattern)}")
    if removals and entries:
        lines.append("")
    for entry in entries:
        lines.append(f"  - label: {_yaml_scalar_str(entry['label'])}")
        lines.append(f"    provider: {_yaml_scalar_str(entry['provider'])}")
        lines.append(f"    model: {_yaml_scalar_str(entry['model'])}")
        params = entry.get("params")
        if params and isinstance(params, dict):
            _write_yaml_value(lines, "params", params, 2)
        lines.append("")
    with open(MODELS_USER_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Model management Script Filter outputs
# ---------------------------------------------------------------------------

_PROVIDERS = [
    {"id": "openai", "name": "OpenAI", "subtitle": "Browse available models"},
    {"id": "anthropic", "name": "Anthropic", "subtitle": "Enter a model ID manually"},
    {"id": "gemini", "name": "Google Gemini", "subtitle": "Browse available models"},
    {"id": "openrouter", "name": "OpenRouter", "subtitle": "Browse available models"},
]


def list_providers_as_alfred_items(query):
    items = []
    for p in _PROVIDERS:
        if (
            query
            and query.lower() not in p["name"].lower()
            and query.lower() not in p["id"]
        ):
            continue
        items.append(
            {
                "uid": p["id"],
                "title": p["name"],
                "subtitle": p["subtitle"],
                "arg": p["id"],
                "icon": {"path": "icon.png"},
            }
        )
    return json.dumps({"items": items})


def list_provider_models_as_alfred_items(provider, query):
    items = []
    if provider == "anthropic":
        if query.strip():
            items.append(
                {
                    "uid": "manual",
                    "title": query,
                    "subtitle": f"Use model ID: {query}",
                    "arg": f"anthropic:{query}",
                    "icon": {"path": "icon.png"},
                }
            )
        else:
            items.append(
                {
                    "uid": "hint",
                    "title": "Type a model ID...",
                    "subtitle": "e.g. claude-sonnet-4-6, claude-opus-4-6",
                    "valid": False,
                    "icon": {"path": "icon.png"},
                }
            )
        return json.dumps({"items": items})

    try:
        models = _fetch_provider_models(provider)
    except RuntimeError as e:
        return json.dumps(
            {
                "items": [
                    {
                        "uid": "error",
                        "title": "Error fetching models",
                        "subtitle": str(e)[:100],
                        "valid": False,
                        "icon": {"path": "icon.png"},
                    }
                ]
            }
        )

    for m in models:
        mid = m["id"]
        name = m["name"]
        display = f"{name} ({mid})" if name != mid else mid
        if query and query.lower() not in display.lower():
            continue
        items.append(
            {
                "uid": mid,
                "title": display,
                "subtitle": mid,
                "arg": f"{provider}:{mid}",
                "icon": {"path": "icon.png"},
            }
        )

    if not items:
        items.append(
            {
                "uid": "empty",
                "title": "No models found" + (f" matching '{query}'" if query else ""),
                "valid": False,
                "icon": {"path": "icon.png"},
            }
        )
    return json.dumps({"items": items})


def label_model_as_alfred_items(provider_model, query):
    # provider_model is "provider:model_id"
    parts = provider_model.split(":", 1)
    provider = parts[0] if len(parts) > 1 else ""
    model_id = parts[1] if len(parts) > 1 else provider_model
    default_label = f"{provider}/{model_id}"

    if query.strip():
        label = query.strip()
        subtitle = f"Custom label for {provider}:{model_id}"
    else:
        label = default_label
        subtitle = "Press Enter to use default, or type a custom label"

    items = [
        {
            "uid": "label",
            "title": label,
            "subtitle": subtitle,
            "arg": label,
            "icon": {"path": "icon.png"},
        }
    ]
    return json.dumps({"items": items})


def list_user_models_as_alfred_items(query):
    entries, _ = _load_user_models_raw()
    items = []
    for entry in entries:
        label = entry.get("label", "")
        provider = entry.get("provider", "")
        model_id = entry.get("model", "")
        if (
            query
            and query.lower() not in label.lower()
            and query.lower() not in model_id.lower()
        ):
            continue
        items.append(
            {
                "uid": label,
                "title": label,
                "subtitle": f"{provider}/{model_id}",
                "arg": label,
                "icon": {"path": "icon.png"},
            }
        )
    if not items:
        items.append(
            {
                "uid": "empty",
                "title": "No user-added models"
                + (f" matching '{query}'" if query else ""),
                "subtitle": "Use llm-add to add models",
                "valid": False,
                "icon": {"path": "icon.png"},
            }
        )
    return json.dumps({"items": items})


# ---------------------------------------------------------------------------
# Model management action handlers
# ---------------------------------------------------------------------------


def handle_add_model(provider_model, label):
    """Add a model to models.yaml."""
    parts = provider_model.split(":", 1)
    if len(parts) != 2:
        notify("LLM Error", f"Invalid model spec: {provider_model}")
        return
    provider, model_id = parts
    entries, removals = _load_user_models_raw()
    # Check for duplicate label
    for e in entries:
        if e.get("label") == label:
            notify("LLM Error", f"Model with label '{label}' already exists")
            return
    entries.append({"label": label, "provider": provider, "model": model_id})
    _save_user_models(entries, removals)
    # Clear the models cache so it reloads
    global _models_cache
    _models_cache = None
    notify("LLM", f"Added model: {label}")


def handle_remove_model(label):
    """Remove a model from models.yaml by label."""
    entries, removals = _load_user_models_raw()
    new_entries = [e for e in entries if e.get("label") != label]
    if len(new_entries) == len(entries):
        notify("LLM Error", f"Model not found: {label}")
        return
    _save_user_models(new_entries, removals)
    global _models_cache
    _models_cache = None
    notify("LLM", f"Removed model: {label}")


def handle_open_config():
    """Open the user data directory in Finder."""
    subprocess.run(["open", DATA_DIR], check=False)


def handle_copy_config_path():
    """Copy the user data directory path to clipboard."""
    _set_clipboard(DATA_DIR)
    notify("LLM", f"Path copied: {DATA_DIR}")


# ---------------------------------------------------------------------------
# Shorthand translation
# ---------------------------------------------------------------------------

_REASONING_BUDGETS = {"high": 10000, "medium": 5000, "low": 2000}


def _translate_shorthands(provider, params):
    """Translate unified shorthands (reasoning, web_search) to provider-native format.
    Returns a new params dict with shorthands removed and native keys added."""
    params = dict(params)
    translated = {}

    # --- reasoning ---
    reasoning = params.pop("reasoning", None)
    if reasoning is not None:
        if provider == "anthropic":
            if reasoning == "auto":
                translated["thinking"] = {"type": "enabled", "budget_tokens": 0}
            elif reasoning in _REASONING_BUDGETS:
                translated["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": _REASONING_BUDGETS[reasoning],
                }
        elif provider in ("openai", "openrouter"):
            if reasoning == "auto":
                translated["reasoning_effort"] = "high"
            else:
                translated["reasoning_effort"] = reasoning
        elif provider == "gemini":
            if reasoning == "auto":
                translated["thinking_config"] = {"thinking_budget": -1}
            elif reasoning in _REASONING_BUDGETS:
                translated["thinking_config"] = {
                    "thinking_budget": _REASONING_BUDGETS[reasoning],
                }

    # --- web_search ---
    web_search = params.pop("web_search", None)
    if web_search:
        if provider == "openai":
            translated["web_search_options"] = {"search_context_size": "medium"}
        elif provider == "anthropic":
            translated.setdefault("tools", []).append({"type": "web_search_20250305"})
        elif provider == "gemini":
            translated.setdefault("tools", []).append({"google_search": {}})
        elif provider == "openrouter":
            translated.setdefault("plugins", []).append("web")

    # Merge: translated first, then raw params override
    result = _deep_merge(translated, params)
    return result


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}

PROVIDER_KEY_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def notify(title, message):
    """Send a macOS notification."""
    script = (
        f'display notification "{_applescript_escape(message)}" '
        f'with title "{_applescript_escape(title)}"'
    )
    subprocess.run(["osascript", "-e", script], check=False)


def _applescript_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def paste_to_frontmost(text):
    """Copy text to clipboard and paste it into the frontmost app."""
    _set_clipboard(text)
    script = """
    tell application "System Events"
        keystroke "v" using command down
    end tell
    """
    subprocess.run(["osascript", "-e", script], check=False)


def _set_clipboard(text):
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    p.communicate(text.encode("utf-8"))


def show_large_type(text):
    """Output text for Alfred Large Type (caller uses alfred_result)."""
    # Alfred large-type is triggered by the calling script filter returning
    # the text as the arg; the info.plist wires it to Large Type action.
    _set_clipboard(text)
    notify("LLM Response", text[:200])


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

STATE_FILE = os.path.join(STATE_DIR, "active_model.json")
CONVERSATION_FILE = os.path.join(STATE_DIR, "last_conversation.json")


def get_active_model():
    """Return the label of the active model."""
    models = get_models_dict()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            label = data.get("model")
            if label in models:
                return label
    # Default: first model
    all_models = load_models()
    return all_models[0]["label"] if all_models else None


def set_active_model(label):
    with open(STATE_FILE, "w") as f:
        json.dump({"model": label}, f)


def save_conversation(messages, model_key):
    with open(CONVERSATION_FILE, "w") as f:
        json.dump({"model": model_key, "messages": messages}, f)


def load_conversation():
    if os.path.exists(CONVERSATION_FILE):
        with open(CONVERSATION_FILE) as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_template(filepath):
    with open(filepath) as f:
        content = f.read()
    meta = {}
    body = content
    m = FRONTMATTER_RE.match(content)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip().lower()] = val.strip()
        body = content[m.end() :]
    return {
        "name": meta.get("name", os.path.splitext(os.path.basename(filepath))[0]),
        "output": meta.get("output", "clipboard"),
        "system": meta.get("system", ""),
        "body": body.strip(),
        "file": filepath,
    }


def load_templates():
    templates = []
    if os.path.isdir(TEMPLATES_DIR):
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if fname.endswith(".txt"):
                templates.append(parse_template(os.path.join(TEMPLATES_DIR, fname)))
    return templates


def get_system_prompt():
    """Return the global system prompt."""
    env_prompt = os.environ.get("LLM_SYSTEM_PROMPT", "")
    if env_prompt:
        return env_prompt
    if os.path.exists(SYSTEM_PROMPT_FILE):
        with open(SYSTEM_PROMPT_FILE) as f:
            return f.read().strip()
    return "You are a helpful assistant."


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def _http_post(url, headers, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body[:300])
        except Exception:
            msg = body[:300]
        raise RuntimeError(f"HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from e


def _http_get(url, headers=None, timeout=30):
    """GET request via urllib, returns parsed JSON."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from e


def call_openai_compatible(
    endpoint, api_key, model_id, system_prompt, messages, params=None
):
    """Call OpenAI-compatible API (OpenAI, OpenRouter)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model_id,
        "messages": [],
    }
    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].extend(messages)

    if params:
        # Messages are special — don't overwrite them
        msgs = payload.pop("messages")
        payload = _deep_merge(payload, params)
        payload["messages"] = msgs

    resp = _http_post(endpoint, headers, payload)
    return resp["choices"][0]["message"]["content"]


def call_anthropic(api_key, model_id, system_prompt, messages, params=None):
    """Call Anthropic Messages API."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model_id,
        "max_tokens": 4096,
        "messages": messages,
    }
    if system_prompt:
        payload["system"] = system_prompt

    if params:
        msgs = payload.pop("messages")
        payload = _deep_merge(payload, params)
        payload["messages"] = msgs

    # If thinking is enabled, bump max_tokens to accommodate
    thinking = payload.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens", 0)
        if budget > 0 and payload.get("max_tokens", 0) < budget + 4096:
            payload["max_tokens"] = budget + 4096

    resp = _http_post(PROVIDER_ENDPOINTS["anthropic"], headers, payload)
    # Extract text from content blocks (thinking responses have multiple blocks)
    content = resp.get("content", [])
    for block in content:
        if block.get("type") == "text":
            return block["text"]
    return content[0]["text"] if content else ""


def call_gemini(api_key, model_id, system_prompt, messages, params=None):
    """Call Google Gemini API."""
    url = PROVIDER_ENDPOINTS["gemini"].format(model=model_id) + f"?key={api_key}"
    headers = {"Content-Type": "application/json"}

    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload: dict[str, object] = {"contents": contents}
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    if params:
        contents_save = payload.pop("contents")
        payload = _deep_merge(payload, params)
        payload["contents"] = contents_save

    resp = _http_post(url, headers, payload)
    return resp["candidates"][0]["content"]["parts"][0]["text"]


def call_llm(label, system_prompt, messages):
    """Route to the correct provider and make the API call."""
    models = get_models_dict()
    model_entry = models[label]
    provider = model_entry["provider"]
    model_id = model_entry["model"]

    key_var = PROVIDER_KEY_VARS[provider]
    api_key = os.environ.get(key_var, "")
    if not api_key:
        raise RuntimeError(
            f"API key not set. Please set the {key_var} environment variable "
            f"in the Alfred workflow configuration."
        )

    # Translate shorthands and prepare merged params
    raw_params = model_entry.get("params")
    params = _translate_shorthands(provider, raw_params) if raw_params else None

    if provider == "openai":
        return call_openai_compatible(
            PROVIDER_ENDPOINTS["openai"],
            api_key,
            model_id,
            system_prompt,
            messages,
            params,
        )
    elif provider == "anthropic":
        return call_anthropic(api_key, model_id, system_prompt, messages, params)
    elif provider == "gemini":
        return call_gemini(api_key, model_id, system_prompt, messages, params)
    elif provider == "openrouter":
        return call_openai_compatible(
            PROVIDER_ENDPOINTS["openrouter"],
            api_key,
            model_id,
            system_prompt,
            messages,
            params,
        )
    else:
        raise RuntimeError(f"Unknown provider: {provider}")


# ---------------------------------------------------------------------------
# Output delivery
# ---------------------------------------------------------------------------


def deliver_output(text, mode):
    if mode == "paste":
        paste_to_frontmost(text)
        notify("LLM", "Response pasted")
    elif mode == "largetype":
        show_large_type(text)
    else:  # clipboard (default)
        _set_clipboard(text)
        notify("LLM", "Response copied to clipboard")


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def handle_ask(query, continue_conversation=False):
    """Handle freeform 'ask' keyword input."""
    model_key = get_active_model()
    system_prompt = get_system_prompt()

    messages = []
    if continue_conversation:
        prev = load_conversation()
        if prev and prev.get("model") == model_key:
            messages = prev.get("messages", [])

    messages.append({"role": "user", "content": query})

    try:
        response = call_llm(model_key, system_prompt, messages)
    except RuntimeError as e:
        notify("LLM Error", str(e))
        return

    messages.append({"role": "assistant", "content": response})
    save_conversation(messages, model_key)
    deliver_output(response, "clipboard")


def handle_template(template_name, input_text):
    """Handle Universal Action with a template."""
    templates = load_templates()
    template = None
    for t in templates:
        if t["name"] == template_name:
            template = t
            break

    if not template:
        notify("LLM Error", f"Template not found: {template_name}")
        return

    prompt = template["body"].replace("{{input}}", input_text)
    system_prompt = template["system"] if template["system"] else get_system_prompt()
    output_mode = template.get("output", "clipboard")
    model_key = get_active_model()

    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(model_key, system_prompt, messages)
    except RuntimeError as e:
        notify("LLM Error", str(e))
        return

    save_conversation(
        messages + [{"role": "assistant", "content": response}], model_key
    )
    deliver_output(response, output_mode)


def list_templates_as_alfred_items(query=""):
    """Return Alfred script filter JSON for template selection."""
    templates = load_templates()
    items = []
    for t in templates:
        name = t["name"]
        if query and query.lower() not in name.lower():
            continue
        items.append(
            {
                "uid": name,
                "title": name,
                "subtitle": f"Output: {t['output']}  |  {t['body'][:80]}...",
                "arg": name,
                "icon": {"path": "icon.png"},
            }
        )
    return json.dumps({"items": items})


TEMPLATE_SKELETON = """\
---
name: {name}
output: clipboard
system:
---
{{{{input}}}}
"""


def manage_templates_list(query=""):
    """Return Alfred script filter JSON for template management."""
    templates = load_templates()
    items = []

    # "Open Templates Folder" — always shown
    if not query or "open" in query.lower() or "folder" in query.lower():
        items.append(
            {
                "uid": "_open_folder",
                "title": "Open Templates Folder",
                "subtitle": TEMPLATES_DIR,
                "arg": "_open_folder",
                "icon": {"path": "icon.png"},
            }
        )

    # "Create new" — shown when the user has typed something
    if query.strip():
        items.insert(
            0,
            {
                "uid": "_create_new",
                "title": f'Create New Template: "{query}"',
                "subtitle": "Creates a new .txt template and opens it for editing",
                "arg": f"_create:{query}",
                "icon": {"path": "icon.png"},
            },
        )

    # Existing templates — edit on select
    for t in templates:
        name = t["name"]
        if query and query.lower() not in name.lower():
            continue
        items.append(
            {
                "uid": name,
                "title": name,
                "subtitle": f"Edit  |  Output: {t['output']}  |  {os.path.basename(t['file'])}",
                "arg": f"_edit:{t['file']}",
                "icon": {"path": "icon.png"},
            }
        )

    return json.dumps({"items": items})


def handle_manage_template(action):
    """Handle a manage-template action (open folder, create, or edit)."""
    if action == "_open_folder":
        subprocess.run(["open", TEMPLATES_DIR], check=False)

    elif action.startswith("_create:"):
        name = action[len("_create:") :]
        filename = (
            re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_").lower() + ".txt"
        )
        filepath = os.path.join(TEMPLATES_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(TEMPLATE_SKELETON.format(name=name))
        subprocess.run(["open", "-t", filepath], check=False)

    elif action.startswith("_edit:"):
        filepath = action[len("_edit:") :]
        if os.path.exists(filepath):
            subprocess.run(["open", "-t", filepath], check=False)
        else:
            notify("LLM Error", f"File not found: {filepath}")


# ---------------------------------------------------------------------------
# CLI dispatcher
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"items": [{"title": "Usage: llm.py <command> [args]"}]}))
        return

    command = sys.argv[1]

    if command == "ask":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not query.strip():
            notify("LLM", "No query provided")
            return
        handle_ask(query)

    elif command == "ask-more":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not query.strip():
            notify("LLM", "No query provided")
            return
        handle_ask(query, continue_conversation=True)

    elif command == "template":
        template_name = sys.argv[2] if len(sys.argv) > 2 else ""
        # Read input text from stdin to avoid putting large text on the
        # command line (visible in ps, subject to ARG_MAX).
        # Falls back to argv[3] for CLI testing.
        if not sys.stdin.isatty():
            input_text = sys.stdin.read()
        elif len(sys.argv) > 3:
            input_text = sys.argv[3]
        else:
            input_text = ""
        if not template_name:
            notify("LLM Error", "No template specified")
            return
        handle_template(template_name, input_text)

    elif command == "list-templates":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(list_templates_as_alfred_items(query))

    elif command == "set-model":
        label = sys.argv[2] if len(sys.argv) > 2 else ""
        models = get_models_dict()
        if label in models:
            set_active_model(label)
            notify("LLM", f"Active model: {label}")
        else:
            notify("LLM Error", f"Unknown model: {label}")

    elif command == "manage-templates":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(manage_templates_list(query))

    elif command == "manage-template-action":
        action = sys.argv[2] if len(sys.argv) > 2 else ""
        if action:
            handle_manage_template(action)

    elif command == "create-template":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        if not name.strip():
            notify("LLM Error", "No template name provided")
            return
        handle_manage_template(f"_create:{name}")

    elif command == "list-providers":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(list_providers_as_alfred_items(query))

    elif command == "list-provider-models":
        provider = sys.argv[2] if len(sys.argv) > 2 else ""
        query = sys.argv[3] if len(sys.argv) > 3 else ""
        print(list_provider_models_as_alfred_items(provider, query))

    elif command == "label-model":
        provider_model = sys.argv[2] if len(sys.argv) > 2 else ""
        query = sys.argv[3] if len(sys.argv) > 3 else ""
        print(label_model_as_alfred_items(provider_model, query))

    elif command == "list-user-models":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(list_user_models_as_alfred_items(query))

    elif command == "add-model":
        provider_model = sys.argv[2] if len(sys.argv) > 2 else ""
        label = sys.argv[3] if len(sys.argv) > 3 else ""
        if not provider_model or not label:
            notify("LLM Error", "Usage: add-model provider:model label")
            return
        handle_add_model(provider_model, label)

    elif command == "remove-model":
        label = sys.argv[2] if len(sys.argv) > 2 else ""
        if not label:
            notify("LLM Error", "No model label provided")
            return
        handle_remove_model(label)

    elif command == "open-config":
        handle_open_config()

    elif command == "copy-config-path":
        handle_copy_config_path()

    else:
        notify("LLM Error", f"Unknown command: {command}")


if __name__ == "__main__":
    main()
