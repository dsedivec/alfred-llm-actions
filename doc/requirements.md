# LLM Workflow for Alfred — Requirements

## Overview

An Alfred 5 workflow that provides keyboard-driven access to LLM APIs (OpenAI, Anthropic, Google Gemini, OpenRouter) for freeform Q&A and text transformation, without leaving the current app. All logic lives in Python scripts invoked by Alfred's script actions and script filters.

## Platform & Runtime Constraints

- **macOS only** — depends on Alfred 5, `osascript`, `pbcopy`, `open`.
- **Python 3.9+** — must work with the system Python shipped by macOS (`/usr/bin/python3`). No f-string features newer than 3.9 (e.g. no backslash escapes in f-string expressions, which requires 3.12+).
- **No external dependencies** — stdlib only. No PyYAML, no `requests`, no pip packages. YAML parsing is handled by a built-in minimal parser. HTTP is done via `urllib.request`.
- **Large text must not appear on the command line** — selected text passed to templates can be arbitrarily large. It must be delivered to the Python process via stdin (using a shell heredoc), not as a CLI argument or environment variable, to avoid `ARG_MAX` limits and `ps` visibility. Short, user-typed keyword arguments (e.g. `ask <query>`) are fine as CLI args.

## Alfred Keywords & Entry Points

Each keyword maps to nodes in `info.plist` and ultimately calls `llm.py <command>` or `select_model.py`.

| Alfred Keyword  | Command                            | Description                                      |
|-----------------|------------------------------------|--------------------------------------------------|
| `ask <query>`   | `llm.py ask "{query}"`             | Freeform Q&A. Response copied to clipboard.      |
| `ask-more <q>`  | `llm.py ask-more "{query}"`        | Continue previous conversation with context.     |
| `llm-model`     | `select_model.py "{query}"`        | Script filter: list models, select to activate.  |
| `llm-templates` | `llm.py manage-templates "{query}"`| Script filter: list/create/edit/open templates.  |
| `llm-new <name>`| `llm.py create-template "{query}"` | Create a new template file and open in editor.   |
| `llm-add`       | `llm.py list-providers "{query}"`  | Script filter chain: browse providers → models → label → add to models.yaml. |
| `llm-remove`    | `llm.py list-user-models "{query}"`| Script filter: list user-added models, select to remove. |
| `llm-config`    | `llm.py open-config`              | Open workflow directory in Finder. ⌘+Enter copies path to clipboard instead. |
| *(Universal Action)* | `llm.py template "{query}"` (stdin) | "Send to LLM": select text → pick template → run. |

### Universal Action Flow

1. User selects text in any app, triggers Universal Action ("Send to LLM").
2. An Arg/Vars node stores the selected text in the `input_text` workflow variable and clears the argument.
3. A script filter shows the template list (user types to filter).
4. On selection, a run script executes: `llm.py template "<template_name>" <<LLMINPUT\n$input_text\nLLMINPUT`. The heredoc pipes text via stdin.
5. Python reads stdin (`sys.stdin.read()`), applies the template, calls the LLM, delivers output.

## Providers

Four providers are supported. Each has a fixed API endpoint, an environment variable for its API key, and provider-specific request/response handling.

| Provider    | Endpoint                                              | Key Variable         | API Style           |
|-------------|-------------------------------------------------------|----------------------|---------------------|
| `openai`    | `https://api.openai.com/v1/chat/completions`          | `OPENAI_API_KEY`     | OpenAI chat format  |
| `anthropic` | `https://api.anthropic.com/v1/messages`               | `ANTHROPIC_API_KEY`  | Anthropic Messages  |
| `gemini`    | `https://generativelanguage.googleapis.com/v1beta/...` | `GEMINI_API_KEY`    | Gemini generateContent |
| `openrouter`| `https://openrouter.ai/api/v1/chat/completions`       | `OPENROUTER_API_KEY` | OpenAI-compatible   |

API keys are set via Alfred's workflow configuration UI (environment variables).

## Model Configuration

### YAML-Based Model List

Models are defined in YAML files, not hardcoded in Python.

- **`models_default.yaml`** — Ships with the workflow. Contains curated defaults. Must not be edited by users (overwritten on update). Included in `package.sh`.
- **`models.yaml`** — Optional user overrides file. Not shipped, not packaged. Lives in the user data directory (see below).

### Model Entry Schema

Each model is a YAML mapping with these fields:

| Field      | Required | Type   | Description                                        |
|------------|----------|--------|----------------------------------------------------|
| `label`    | Yes      | string | Display name in Alfred. Serves as the unique identifier across the entire model list. |
| `provider` | Yes      | string | One of: `openai`, `anthropic`, `gemini`, `openrouter` |
| `model`    | Yes      | string | The model ID sent to the provider's API            |
| `params`   | No       | dict   | Arbitrary key-value pairs deep-merged into the API request body |

### User Override Mechanics

`models.yaml` entries are processed after loading defaults. Entries are separated into removals and additions — position in the list doesn't matter:

- A normal entry (with `label`, `provider`, `model`) is **appended** to the model list.
- An entry with `remove_defaults: "<pattern>"` **removes** default models whose label matches the pattern. `remove` is accepted as a shorthand alias for `remove_defaults`. Supports glob patterns (`*`, `?`, `[seq]`, `[!seq]`) via `fnmatch.fnmatchcase` (case-sensitive). Removals only affect models from `models_default.yaml`, never user-added entries in the same file.
- `remove_defaults: "*"` removes all defaults, letting you start from scratch with only your own entries.
- Entries missing a `label` key (that aren't removals) are silently skipped.
- There is no "replace" — to change a default, remove it and add a new entry.

### Active Model State

- Stored in `state/active_model.json` as `{"model": "<label>"}`.
- Keyed by **label** (the display name), not by provider/model ID.
- If the stored label doesn't match any loaded model, falls back to the first model in the list.
- Persists across invocations until changed.

### Model Selection Display

In the `llm-model` script filter:

- Title: `label` (prefixed with `✓ ` if active)
- Subtitle: `provider/model_id` plus params summary if present, plus `[ACTIVE]` tag
- Active model sorted to top
- Filterable by label or provider/model string

## Params & Shorthand Translation

The `params` dict on a model entry is deep-merged into the provider's API request body. Before merging, two unified shorthands are translated to provider-native format.

### Deep Merge Behavior

- Dicts are merged recursively (keys in override replace keys in base; non-overlapping keys are preserved).
- Non-dict values (lists, scalars) are replaced wholesale by the override.
- The merge order is: (1) base request built by the provider function, (2) translated shorthands, (3) raw `params`. Raw params always win.
- Special care: `messages` (OpenAI/OpenRouter) and `contents` (Gemini) are never overwritten by params — they are removed before merge and restored after.

### `reasoning` Shorthand

Values: `auto`, `high`, `medium`, `low`.

| Provider    | Translation                                                                 |
|-------------|-----------------------------------------------------------------------------|
| `anthropic` | `thinking: {type: "enabled", budget_tokens: N}` — `auto` uses `budget_tokens: 0` (API auto mode); `high`=10000, `medium`=5000, `low`=2000 |
| `openai`    | `reasoning_effort: "<level>"` — `auto` maps to `"high"`                     |
| `gemini`    | `thinking_config: {thinking_budget: N}` — `auto` uses `-1`; high/medium/low same as Anthropic |
| `openrouter`| `reasoning_effort: "<level>"` — same as OpenAI                              |

For Anthropic, when thinking is enabled with `budget_tokens > 0`, `max_tokens` is automatically bumped to at least `budget + 4096` if it would otherwise be too small.

### `web_search` Shorthand

Value: `true`.

| Provider    | Translation                                           |
|-------------|-------------------------------------------------------|
| `openai`    | `web_search_options: {search_context_size: "medium"}`  |
| `anthropic` | `tools: [{type: "web_search_20250305"}]`               |
| `gemini`    | `tools: [{google_search: {}}]`                         |
| `openrouter`| `plugins: ["web"]`                                     |

### Pass-Through Params

Any key in `params` that is not `reasoning` or `web_search` is passed through as-is into the request body. This covers provider-specific options like `temperature`, `top_p`, `max_tokens`, OpenRouter's `provider` routing config, etc.

## YAML Parser

A built-in minimal YAML parser handles the model config files. It supports:

- Mappings (`key: value`)
- Lists (`- item`)
- Nested mappings and lists (indent-based)
- Inline flow sequences (`[item1, item2]`)
- Strings (plain, single-quoted, double-quoted)
- Numbers (int, float)
- Booleans (`true`/`false`, `yes`/`no`)
- Null (`null`, `~`)
- Comments (`#`, respecting quoted strings)

It does **not** support: anchors/aliases, multi-line strings (`|`, `>`), complex flow mappings, tags, or other advanced YAML features. The config files must stay within this subset.

## Templates

### Template Files

Templates are `.txt` files in the `templates/` directory. They are discovered by scanning the directory at runtime (sorted alphabetically by filename).

### Template Format

```
---
name: Display Name
output: clipboard
system: Optional system prompt override
---
Prompt body with {{input}} placeholder
```

**Frontmatter fields:**

| Field    | Required | Default              | Description                                     |
|----------|----------|----------------------|-------------------------------------------------|
| `name`   | No       | Filename without ext | Display name in Alfred                          |
| `output` | No       | `clipboard`          | One of: `clipboard`, `paste`, `largetype`       |
| `system` | No       | *(empty)*            | System prompt for this template; overrides global if set |

The `{{input}}` placeholder in the body is replaced with the selected text (Universal Action) or typed input.

### Output Modes

| Mode        | Behavior                                                        |
|-------------|-----------------------------------------------------------------|
| `clipboard` | Response copied to clipboard. macOS notification confirms.      |
| `paste`     | Response copied to clipboard, then pasted into frontmost app via simulated Cmd+V. |
| `largetype` | Response copied to clipboard and shown in a macOS notification (first 200 chars). |

### Built-in Templates

Six templates ship with the workflow:

| Template                  | Output    | Purpose                                 |
|---------------------------|-----------|-----------------------------------------|
| Summarize                 | clipboard | Concise summary of selected text        |
| Rewrite / Improve Writing | paste     | Improve clarity and readability         |
| Fix Grammar & Spelling    | paste     | Fix errors, preserve voice              |
| Change Tone               | clipboard | Rewrite in professional tone            |
| Translate to English      | clipboard | Translate to English                    |
| Break into Bullet List    | clipboard | Restructure as bullets                  |

### Template Management

- **`llm-templates` keyword** — Script filter that lists existing templates (select to edit), offers "Create New Template" when text is typed, and shows "Open Templates Folder".
- **`llm-new <name>` keyword** — Creates a new template file from a skeleton and opens it in the default `.txt` editor. The filename is derived from the name: special characters stripped, spaces replaced with underscores, lowercased, `.txt` appended.
- Template creation writes a skeleton with frontmatter (`name`, `output: clipboard`, empty `system`) and `{{input}}` placeholder.
- Editing opens the file with `open -t` (default text editor for `.txt` on macOS).

### Template Skeleton

When creating a new template (via `llm-new` or `llm-templates`), the generated file contains:

```
---
name: <user-provided name>
output: clipboard
system:
---
{{input}}
```

## Model Management (llm-add, llm-remove, llm-config)

Three Alfred keywords let users manage `models.yaml` without editing it by hand.

### Add Model Flow (`llm-add`)

A 6-node chain in `info.plist`:

```
[llm-add Script Filter] → [Arg/Vars: save provider] → [Model List Script Filter]
  → [Arg/Vars: save model] → [Label Script Filter] → [Run Script: add-model]
```

1. **Provider selection** — Script filter lists 4 providers (OpenAI, Anthropic, Gemini, OpenRouter), filtered by query.
2. **Arg/Vars** — Saves selected provider to `$selected_provider`, clears arg.
3. **Model list** — Script filter calls `llm.py list-provider-models "$selected_provider" "{query}"`. For Anthropic, shows a hint and accepts typed text as a manual model ID. For others, fetches/caches the provider's model list and filters locally.
4. **Arg/Vars** — Saves `provider:model_id` to `$selected_model`, clears arg.
5. **Label entry** — Script filter calls `llm.py label-model "$selected_model" "{query}"`. Shows default label `provider/model_id`. If user types, shows their custom label instead. Enter confirms.
6. **Run script** — Calls `llm.py add-model "$selected_model" "{query}"`. Appends entry to `models.yaml`, sends notification.

### Remove Model Flow (`llm-remove`)

A 2-node chain:

```
[llm-remove Script Filter] → [Run Script: remove-model]
```

1. **Model list** — Script filter calls `llm.py list-user-models "{query}"`. Shows only models from the user's `models.yaml` (not defaults).
2. **Run script** — Calls `llm.py remove-model "{query}"`. Removes the entry by label, sends notification.

### Open Config (`llm-config`)

A keyword with two connections:

```
[llm-config Keyword] → [Run Script: open-config]       (default: Enter)
                      → [Run Script: copy-config-path]  (⌘+Enter)
```

- **Enter** — Opens the user data directory in Finder.
- **⌘+Enter** — Copies the user data directory path to clipboard and sends a notification.

The ⌘ modifier is implemented via a second connection with `modifiers: 1048576` (NSEventModifierFlagCommand) pointing to a separate run script node.

### Provider Model Fetching

`_http_get(url, headers, timeout)` performs GET requests via `urllib` (analogous to the existing `_http_post`).

`_fetch_provider_models(provider)` returns a list of `{id, name}` dicts:

| Provider    | Source                                          | Notes                                           |
|-------------|-------------------------------------------------|-------------------------------------------------|
| `openai`    | `GET /v1/models` (auth via Bearer token)        | Filters out non-chat models (dall-e, whisper, tts, embedding, etc.) |
| `gemini`    | `GET /v1beta/models?key=...`                    | Extracts model ID (strips `models/` prefix) and displayName |
| `openrouter`| `GET /api/v1/models` (no auth required)         | Extracts id and name, sorted by name            |
| `anthropic` | Returns empty list                              | Manual model ID entry only, handled in the Script Filter UI |

### Provider Model Cache

Fetched model lists are cached to `state/models_cache_{provider}.json` to avoid redundant API calls during browsing.

- Cache file stores `{"timestamp": <epoch>, "models": [...]}`.
- TTL is 3600 seconds (1 hour). Expired or missing caches trigger a fresh fetch.
- All filtering is done locally on the cached list.

### YAML Writer

A string-based YAML writer (`_save_user_models`) serializes structured model data back to `models.yaml`. It handles:

- `remove_defaults` entries (written first)
- Model entries with `label`, `provider`, `model`, and optional `params`
- Nested dicts and lists in `params` (recursive)
- Proper quoting of scalars that contain special YAML characters

The writer is used by `add-model` and `remove-model`. It always rewrites the entire file from the parsed data (read via `_load_user_models_raw`), preserving both removal entries and model entries.

## User Data Directory

User-mutable files (`models.yaml`, state, and cache) are stored outside the workflow directory so they survive workflow updates (which replace the entire workflow directory).

### Location

- **In Alfred:** Uses the `alfred_workflow_data` environment variable, which points to `~/Library/Application Support/Alfred/Workflow Data/<bundle_id>/`.
- **CLI fallback:** When `alfred_workflow_data` is not set, falls back to `<workflow_dir>/data/`.

### Directory Layout

```
<data_dir>/
  models.yaml                           # User model overrides
  state/
    active_model.json                   # Currently selected model
    last_conversation.json              # Last conversation for ask-more
    models_cache_{provider}.json        # Cached provider model lists
```

### Auto-Migration

On first run after a workflow update, if the data directory is external (not inside the workflow directory), existing user files are automatically migrated:

- `models.yaml` is copied from the workflow directory to the data directory.
- All files in the workflow's `state/` directory are copied to the data directory's `state/` subdirectory.
- Existing files in the data directory are **never** overwritten — only missing files are copied.

## Conversation State

- The last conversation (messages + model label) is saved to `state/last_conversation.json`.
- `ask-more` loads the previous conversation if the active model matches the stored model, then appends the new user message. This provides multi-turn context.
- `ask` starts a fresh conversation (single-turn), but still saves it for potential `ask-more` follow-up.
- Template invocations also save their exchange as a conversation.

## System Prompt

A global system prompt applies to all invocations unless a template provides its own.

**Priority order (highest wins):**
1. Template's `system` frontmatter field (if non-empty)
2. `LLM_SYSTEM_PROMPT` environment variable (set via Alfred workflow config)
3. `system_prompt.txt` file in the workflow directory
4. Hardcoded fallback: `"You are a helpful assistant."`

## Error Handling

- API errors (HTTP errors, network failures) are caught and shown as macOS notifications via `osascript`.
- No automatic retry or fallback to another provider.
- If the API key for the active model's provider is not set, a notification explains which environment variable to set.

## Notifications

All user-facing feedback (success confirmations, errors) is delivered via macOS notifications using `osascript` / `display notification`. Special characters are escaped for AppleScript.

## Packaging

`package.sh` creates a `.alfredworkflow` file (zip archive) containing:
- `info.plist`, `llm.py`, `select_model.py`, `models_default.yaml`, `system_prompt.txt`, `templates/`, `README.md`

Excluded: `*.pyc`, `__pycache__/`, `state/`, `data/`, `models.yaml` (user files, not shipped).

## info.plist Structure

The Alfred workflow definition (`info.plist`) defines:

- **Keyword inputs:** `ask`, `ask-more`, `llm-model`, `llm-templates`, `llm-new`, `llm-config`
- **Script filters:** model selection (`select_model.py`), template listing, manage-templates, provider listing (`llm-add`), provider model listing, label entry, user model listing (`llm-remove`)
- **Run script actions:** for ask, ask-more, set-model, template execution, manage-template actions, create-template, add-model, remove-model, open-config, copy-config-path
- **Universal Action trigger:** accepts text, wired through Arg/Vars → template list → template run
- **Arg/Vars utilities:** (1) stores Universal Action text in `input_text` variable; (2) stores selected provider in `selected_provider` variable; (3) stores `provider:model_id` in `selected_model` variable. Each clears the argument so the next script filter receives an empty query.
- **Modifier connections:** `llm-config` keyword has two outgoing connections — default (Enter) to open-config, and ⌘ (modifier 1048576) to copy-config-path
- **User configuration:** text fields for each API key and the system prompt (`LLM_SYSTEM_PROMPT`)
- **Node UIDs:** use the pattern `A1B2C3D4-<DESCRIPTIVE-NAME>` for readability

### Script Invocation Patterns

| Pattern | Used For | Notes |
|---------|----------|-------|
| `/usr/bin/python3 llm.py <cmd> "{query}"` | Most commands | Short user-typed text is fine as argv |
| `/usr/bin/python3 llm.py template "{query}" <<LLMINPUT\n$input_text\nLLMINPUT` | Template execution | Heredoc pipes large text via stdin |
| `/usr/bin/python3 select_model.py "{query}"` | Model selection | Script filter returning Alfred JSON |
| `/usr/bin/python3 llm.py list-provider-models "$selected_provider" "{query}"` | Model browsing | Provider passed via workflow variable |
| `/usr/bin/python3 llm.py add-model "$selected_model" "{query}"` | Add model | Model spec via variable, label via query |
| `/usr/bin/python3 llm.py open-config` | Open config | No arguments |
| `/usr/bin/python3 llm.py copy-config-path` | Copy config path | No arguments, triggered via ⌘ modifier |

## File Layout

```
llm_actions/
  info.plist              # Alfred workflow definition
  llm.py                  # Main script: API calls, templates, state, YAML parser, CLI dispatcher
  select_model.py         # Model selection script filter (imports from llm.py)
  models_default.yaml     # Default model list (shipped)
  system_prompt.txt       # Default global system prompt
  package.sh              # Builds .alfredworkflow zip
  README.md               # User-facing documentation
  templates/              # Prompt template .txt files
    summarize.txt
    rewrite.txt
    fix_grammar.txt
    change_tone.txt
    translate.txt
    bullet_list.txt
  data/                   # Fallback user data dir (CLI mode, gitignored, not shipped)
    models.yaml            # User overrides
    state/
      active_model.json
      last_conversation.json
      models_cache_{provider}.json
  doc/
    requirements.md       # This file
```
