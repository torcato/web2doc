#!/usr/bin/env bash
set -Eeuo pipefail

# Run an end-to-end, user-documentation-oriented generation:
# discover -> draft workflows -> verify -> generate revisions -> create review bundles.
# Publication remains deliberately manual: an owner must approve each document first.

usage() {
  echo "Usage: $0 PROJECT_DIR [options]"
  echo
  echo "Options:"
  echo "  --role ROLE                 Role to explore (default: default)"
  echo "  --max-actions N             Discovery action budget"
  echo "  --max-states N              Discovery state budget"
  echo "  --max-seconds N             Discovery wall-clock budget"
  echo "  --model MODEL               Pydantic AI discovery model"
  echo "  --headed                    Show the browser during discovery and verification"
  echo "  --trusted-fixture-api       Enable /__prepare, /__state, and /__reset during verification"
  echo "  -h, --help                 Show this help"
}

if [[ $# -lt 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  usage >&2
  [[ $# -ge 1 ]] && exit 0
  exit 2
fi

PROJECT_DIR=$1
shift
ROLE=default
DISCOVER_ARGS=()
VERIFY_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)
      ROLE=$2
      shift 2
      ;;
    --max-actions|--max-states|--max-seconds|--model)
      DISCOVER_ARGS+=("$1" "$2")
      shift 2
      ;;
    --headed)
      DISCOVER_ARGS+=("--headed")
      VERIFY_ARGS+=("--headed")
      shift
      ;;
    --trusted-fixture-api)
      VERIFY_ARGS+=("--trusted-fixture-api")
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to parse web2doc command output." >&2
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/project.toml" ]]; then
  echo "Project file not found: $PROJECT_DIR/project.toml" >&2
  echo "Create a project first with: uv run web2doc init NAME --base-url URL --path $PROJECT_DIR" >&2
  exit 1
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

run_cli() {
  uv run web2doc "$@"
}

echo "[1/5] Discovering user-facing capabilities..."
run_cli discover "$PROJECT_DIR" --role "$ROLE" --mode unguided "${DISCOVER_ARGS[@]}" \
  | tee "$TMP_DIR/discovery.json"
DISCOVERY_RUN_ID=$(jq -r '.run.id' "$TMP_DIR/discovery.json")
DISCOVERY_STATUS=$(jq -r '.run.status' "$TMP_DIR/discovery.json")
if [[ "$DISCOVERY_STATUS" != "awaiting_review" && "$DISCOVERY_STATUS" != "completed" ]]; then
  echo "Discovery did not finish safely (status: $DISCOVERY_STATUS, run: $DISCOVERY_RUN_ID)." >&2
  echo "Inspect it with: uv run web2doc discovery-report $PROJECT_DIR $DISCOVERY_RUN_ID" >&2
  exit 1
fi

echo "[2/5] Drafting concise user tasks from the exploration..."
run_cli workflow-draft "$PROJECT_DIR" "$DISCOVERY_RUN_ID" --role "$ROLE" \
  | tee "$TMP_DIR/workflows.json" >/dev/null
WORKFLOW_COUNT=$(jq 'length' "$TMP_DIR/workflows.json")
if [[ "$WORKFLOW_COUNT" == "0" ]]; then
  echo "No workflow tasks were discovered. Review the discovery report: $DISCOVERY_RUN_ID" >&2
  exit 1
fi
echo "Drafted $WORKFLOW_COUNT task(s)."

echo "[3/5] Verifying each drafted task..."
PASSED=0
GENERATED=0
while IFS= read -r REVISION_ID; do
  [[ -z "$REVISION_ID" ]] && continue
  VERIFY_JSON=$(run_cli verify "$PROJECT_DIR" "$REVISION_ID" "${VERIFY_ARGS[@]}")
  VERIFY_STATUS=$(jq -r '.status' <<<"$VERIFY_JSON")
  VERIFY_ID=$(jq -r '.id' <<<"$VERIFY_JSON")
  TITLE=$(jq -r ".[] | select(.id == \"$REVISION_ID\") | .definition.title" "$TMP_DIR/workflows.json")
  if [[ "$VERIFY_STATUS" != "passed" ]]; then
    echo "  SKIP: $TITLE ($VERIFY_STATUS; verification $VERIFY_ID)" >&2
    continue
  fi
  PASSED=$((PASSED + 1))

  echo "[4/5] Generating documentation: $TITLE"
  DOCUMENT_JSON=$(run_cli document-generate "$PROJECT_DIR" "$REVISION_ID" --verification "$VERIFY_ID")
  DOCUMENT_ID=$(jq -r '.id' <<<"$DOCUMENT_JSON")
  BUNDLE_PATH=$(run_cli document-bundle "$PROJECT_DIR" "$DOCUMENT_ID")
  echo "  Review bundle: $BUNDLE_PATH"
  GENERATED=$((GENERATED + 1))
done < <(jq -r '.[].id' "$TMP_DIR/workflows.json")

echo "[5/5] Writing documentation coverage..."
run_cli documentation-coverage "$PROJECT_DIR" | jq '{json_path, markdown_path}'

echo
echo "Completed: $GENERATED generated document(s) from $PASSED passing verification(s)."
echo "Each document needs owner review before it can be exported."
echo "Review with:"
echo "  uv run web2doc document-review $PROJECT_DIR DOCUMENT_REVISION_ID \\"
echo "    --decision approved --reviewer \"Name\" --notes \"Reviewed against evidence\""
echo "Then export approved guides with:"
echo "  uv run web2doc docs-export $PROJECT_DIR ./published-documentation"
