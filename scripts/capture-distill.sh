#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 PROJECT_DIR [options]"
  echo
  echo "Run autonomous discovery, freeze its evidence, and distill offline feature drafts."
  echo
  echo "Options:"
  echo "  --role ROLE                       Role to explore (default: default)"
  echo "  --model MODEL                     Pydantic AI discovery model"
  echo "  --max-actions N                   Discovery action budget"
  echo "  --max-states N                    Discovery state budget"
  echo "  --max-seconds N                   Discovery wall-clock budget"
  echo "  --max-candidates-per-state N      Candidate limit for each state"
  echo "  --headed                          Show the discovery browser"
  echo "  -h, --help                        Show this help"
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)
      ROLE=$2
      shift 2
      ;;
    --model|--max-actions|--max-states|--max-seconds|--max-candidates-per-state)
      DISCOVER_ARGS+=("$1" "$2")
      shift 2
      ;;
    --headed)
      DISCOVER_ARGS+=("--headed")
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
  exit 1
fi

TASK_TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TASK_TEMP_DIR"' EXIT

run_cli() {
  uv run web2doc "$@"
}

echo "[1/3] Running autonomous discovery..."
run_cli discover "$PROJECT_DIR" --role "$ROLE" --mode unguided "${DISCOVER_ARGS[@]}" \
  | tee "$TASK_TEMP_DIR/discovery.json"

DISCOVERY_RUN_ID=$(jq -er '.run.id' "$TASK_TEMP_DIR/discovery.json")
DISCOVERY_STATUS=$(jq -r '.run.status' "$TASK_TEMP_DIR/discovery.json")
STOP_REASON=$(jq -r '.run.stop_reason // "none"' "$TASK_TEMP_DIR/discovery.json")

echo "[2/3] Freezing captured evidence..."
run_cli capture-freeze "$PROJECT_DIR" "$DISCOVERY_RUN_ID" \
  | tee "$TASK_TEMP_DIR/manifest.json" >/dev/null
MANIFEST_ID=$(jq -er '.id' "$TASK_TEMP_DIR/manifest.json")
MANIFEST_VERSION=$(jq -er '.version' "$TASK_TEMP_DIR/manifest.json")
PARTIAL=$(jq -r '.content.partial' "$TASK_TEMP_DIR/manifest.json")

echo "[3/3] Distilling feature drafts without a browser..."
run_cli distill "$PROJECT_DIR" --run "$DISCOVERY_RUN_ID" \
  | tee "$TASK_TEMP_DIR/distillation.json"

PROCESSING_ATTEMPT_ID=$(jq -er '.processing_attempt_id' "$TASK_TEMP_DIR/distillation.json")
FEATURE_COUNT=$(jq '.features | length' "$TASK_TEMP_DIR/distillation.json")
REUSED=$(jq -r '.reused' "$TASK_TEMP_DIR/distillation.json")

echo
echo "Capture and distillation completed."
echo "  Discovery run:       $DISCOVERY_RUN_ID"
echo "  Discovery status:    $DISCOVERY_STATUS"
echo "  Discovery stop:      $STOP_REASON"
echo "  Capture manifest:    $MANIFEST_ID (version $MANIFEST_VERSION, partial: $PARTIAL)"
echo "  Processing attempt:  $PROCESSING_ATTEMPT_ID (reused: $REUSED)"
echo "  Feature drafts:      $FEATURE_COUNT"
echo
echo "Inspect the run with:"
echo "  uv run web2doc discovery-report $PROJECT_DIR $DISCOVERY_RUN_ID"
