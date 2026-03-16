#!/bin/bash
# Package the workflow into a .alfredworkflow file (which is just a zip)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="$SCRIPT_DIR/LLM Workflow.alfredworkflow"

cd "$SCRIPT_DIR"

zip -r "$OUTPUT" \
    info.plist \
    llm.py \
    select_model.py \
    models_default.yaml \
    system_prompt.txt \
    templates/ \
    README.md \
    -x "*.pyc" "__pycache__/*" "state/*" "models.yaml"

echo "Packaged: $OUTPUT"
