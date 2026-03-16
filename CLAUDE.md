# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An Alfred 5 workflow that sends prompts and selected text to LLMs (OpenAI, Anthropic, Gemini, OpenRouter) via keyboard shortcuts. All logic is Python, invoked by Alfred's script actions/filters.

## Constraints

- **Python 3.9+** — must work with macOS system Python (`/usr/bin/python3`). No f-string features requiring 3.12+ (e.g. no backslash escapes in f-string expressions).
- **No external dependencies** — stdlib only. No PyYAML, no `requests`. YAML is parsed by a built-in minimal parser in `llm.py`. HTTP via `urllib.request`.
- **macOS only** — uses `osascript`, `pbcopy`, `open`.
- **Large text via stdin** — selected text is passed to Python via shell heredoc, never as CLI args or env vars (ARG_MAX / `ps` visibility).

## Packaging

```bash
./package.sh
```
Creates `LLM Workflow.alfredworkflow` (a zip). Excludes `*.pyc`, `__pycache__/`, `state/`, `models.yaml`.

## Architecture

**`llm.py`** — Single monolithic script (~1100 lines). Contains everything: CLI dispatcher, YAML parser/writer, 4 provider API implementations, template engine, state management, model config loading/merging, Alfred JSON output, macOS notification delivery. Entry point is `main()` which dispatches on `sys.argv[1]` (command name).

**`select_model.py`** — Small script filter for `llm-model` keyword. Imports `load_models` and `get_active_model` from `llm.py`.

**`info.plist`** — Alfred workflow definition. Node UIDs use pattern `A1B2C3D4-<DESCRIPTIVE-NAME>`. Connections, script filters, run scripts, arg/vars nodes, and universal action trigger are all defined here.

### Key flows in info.plist
- `ask`/`ask-more`: keyword → run script (simple 2-node)
- Universal Action: trigger → arg/vars (saves text to `$input_text`) → template list filter → run script (heredoc pipes stdin)
- `llm-add`: 6-node chain — provider filter → argvars → model filter → argvars → label filter → run script
- `llm-config`: keyword with modifier connections (Enter = open, ⌘ = copy path)

### Model config
- `models_default.yaml` — shipped defaults (do not edit by hand)
- `models.yaml` — user overrides, supports `remove_defaults: "<glob>"` entries
- Merge: defaults loaded first, then user removals applied, then user additions appended
- Active model stored in `state/active_model.json` keyed by label

### YAML parser limitations
The built-in parser supports mappings, lists, scalars, inline flow sequences, comments. Does **not** support: anchors/aliases, multi-line strings (`|`, `>`), flow mappings, tags.

### Params shorthands
`reasoning` and `web_search` in model `params` are translated to provider-native format before being deep-merged into the API request. Raw provider params override shorthands.

## Testing

### Running tests

```bash
uv run --with pytest pytest tests/ -v
```

The test suite uses **pytest** with `tmp_path` and `monkeypatch` for isolation. All tests run on Linux (no macOS dependencies). API tests mock `_http_post`/`_http_get` — no real API keys needed.

For manual smoke tests that hit real APIs:
```bash
python3 llm.py list-templates ""
python3 select_model.py ""
```
API calls require keys set as env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`).

### Development workflow

- **Red/green development is mandatory.** Always write failing tests first, then write the implementation to make them pass. Do not write implementation code without a corresponding test.
- **You are not done until:**
  1. Tests exist for all new functionality.
  2. All tests pass — both new and existing (`uv run --with pytest pytest tests/ -v`).
  3. All changes are committed. A task is **never** finished until the work is committed.
- **Commit often.** During multi-step plans, commit at each logical milestone (e.g. after a feature is working, after a refactor pass, after tests are green). Do not accumulate a large uncommitted diff across many steps.
- When modifying existing behavior, update or add tests to cover the change **before** changing the implementation.
- Mock macOS-only functions (`notify`, `_set_clipboard`, `paste_to_frontmost`) in tests that would otherwise call them. The `conftest.py` fixtures handle path isolation and cache reset automatically.

### Test structure

```
tests/
  conftest.py               # Shared fixtures (path patching, cache reset, file writers)
  test_yaml.py              # _parse_yaml, _yaml_scalar_str, _write_yaml_value
  test_deep_merge.py        # _deep_merge
  test_shorthands.py        # _translate_shorthands (4 providers × reasoning/web_search)
  test_models.py            # load_models (defaults, user additions, remove_defaults globs)
  test_templates.py         # parse_template, load_templates
  test_state.py             # get/set_active_model, save/load_conversation
  test_alfred_items.py      # list_providers_as_alfred_items, label_model_as_alfred_items
  test_api.py               # call_openai_compatible, call_anthropic, call_gemini (mocked HTTP)
  test_cli.py               # main() dispatcher wiring
```
