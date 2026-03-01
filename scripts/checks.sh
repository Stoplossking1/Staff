#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

errors=()
warnings=()

require_cmd() {
  local cmd="$1"
  local hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    errors+=("Missing command '$cmd' (${hint})")
  fi
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    errors+=("Missing required env var '$name'")
  fi
}

warn_if_placeholder() {
  local name="$1"
  if [[ "${!name:-}" == *"your_"* || "${!name:-}" == sk-your-* || "${!name:-}" == lmnr_your_* ]]; then
    warnings+=("Env var '$name' still uses a placeholder value")
  fi
}

require_cmd node "install Node.js 20.19+ or 22.12+"
require_cmd npm "comes with Node.js"
require_cmd curl "required by scripts/run_local.sh health check"
require_cmd python3 "required for agent loop and Laminar instrumentation"

if command -v node >/dev/null 2>&1; then
  node_version="$(node -p 'process.versions.node')"
  if ! node -e '
    const [major, minor] = process.versions.node.split(".").map(Number);
    const ok20 = major === 20 && minor >= 19;
    const ok22 = major >= 22 && (major > 22 || minor >= 12);
    process.exit(ok20 || ok22 ? 0 : 1);
  '; then
    errors+=("Node.js ${node_version} is not supported. Use 20.19+ or 22.12+.")
  fi
fi

if [[ ! -f "$ROOT_DIR/f1-stream/package.json" ]]; then
  errors+=("Missing f1-stream/package.json (stream app not found)")
fi

require_env OPENAI_API_KEY
require_env LMNR_PROJECT_API_KEY
require_env BROWSER_USE_API_KEY
require_env AGENT_LOOP_CMD
warn_if_placeholder OPENAI_API_KEY
warn_if_placeholder LMNR_PROJECT_API_KEY
warn_if_placeholder BROWSER_USE_API_KEY

BROWSER_USE_MCP_MODE="${BROWSER_USE_MCP_MODE:-local}"
if [[ "$BROWSER_USE_MCP_MODE" != "local" && "$BROWSER_USE_MCP_MODE" != "remote" ]]; then
  errors+=("BROWSER_USE_MCP_MODE must be 'local' or 'remote' (got '$BROWSER_USE_MCP_MODE')")
fi

if [[ "$BROWSER_USE_MCP_MODE" == "local" ]]; then
  require_env BROWSER_USE_MCP_COMMAND
  require_env BROWSER_USE_MCP_ARGS
  if [[ -n "${BROWSER_USE_MCP_COMMAND:-}" ]]; then
    if ! command -v "$BROWSER_USE_MCP_COMMAND" >/dev/null 2>&1; then
      warnings+=("Local MCP mode selected but '$BROWSER_USE_MCP_COMMAND' is not installed")
    fi
  fi
else
  require_env BROWSER_USE_MCP_URL
fi

if [[ -n "${AGENT_LOOP_CMD:-}" ]]; then
  agent_cmd_bin="${AGENT_LOOP_CMD%% *}"
  if [[ -n "$agent_cmd_bin" ]] && ! command -v "$agent_cmd_bin" >/dev/null 2>&1; then
    errors+=("Agent command binary '$agent_cmd_bin' not found (from AGENT_LOOP_CMD)")
  fi
fi

if [[ -n "${STREAM_URL:-}" ]] && [[ "${STREAM_URL}" != http://* && "${STREAM_URL}" != https://* ]]; then
  errors+=("STREAM_URL must start with http:// or https://")
fi

if command -v python3 >/dev/null 2>&1; then
  if ! python3 - <<'PY' >/dev/null 2>&1
import importlib.util
import sys
sys.exit(0 if importlib.util.find_spec("lmnr") else 1)
PY
  then
    warnings+=("Python package 'lmnr' not installed (Laminar spans disabled; install with: python3 -m pip install -U lmnr)")
  fi
fi

if [[ ${#errors[@]} -gt 0 ]]; then
  printf "\nLocal setup checks failed:\n"
  for err in "${errors[@]}"; do
    printf "  - %s\n" "$err"
  done
  printf "\nFix the items above, then re-run ./scripts/checks.sh\n"
  exit 1
fi

if [[ ${#warnings[@]} -gt 0 ]]; then
  printf "\nWarnings:\n"
  for warning in "${warnings[@]}"; do
    printf "  - %s\n" "$warning"
  done
fi

printf "All local setup checks passed.\n"
