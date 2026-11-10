#!/usr/bin/env bash
# Baseline Audit (Before Hardening) - 30 tieu chi CIS NGINX Benchmark v3.0.0 (TV3)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=audit/cis_audit_common.sh
source "${SCRIPT_DIR}/cis_audit_common.sh"

run_cis_audit "before" "${PROJECT_ROOT}"
