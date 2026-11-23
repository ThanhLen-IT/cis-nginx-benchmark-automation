#!/usr/bin/env bash
set -euo pipefail
run_cis_audit() {
  local stage="$1" project_root="$2"
  exec "$project_root/cisctl" audit --stage "$stage" "${@:3}"
}
