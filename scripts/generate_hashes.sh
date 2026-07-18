#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

HASH_FILE_NAME="SHA256:hash.txt"

MODULES=(
  "XKernel:XKernel.py"
  "XPatchKernelManager:XPatchKernelManager.py"
  "__init__:lib/custom/XKernel/__init__.py"
  "mac_types:lib/custom/XKernel/mac_types.py"
  "mac_policy:lib/custom/XKernel/mac_policy.py"
  "mac_context:lib/custom/XKernel/mac_context.py"
  "mac_enforcer:lib/custom/XKernel/mac_enforcer.py"
  "mac_hooks:lib/custom/XKernel/mac_hooks.py"
)

sha256_file() {
  local path="$1"

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "${path}" | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -- "${path}" | awk '{print $1}'
    return
  fi

  printf 'error: sha256sum or shasum is required\n' >&2
  return 1
}

for item in "${MODULES[@]}"; do
  module="${item%%:*}"
  relative_path="${item#*:}"
  source_path="${REPO_ROOT}/${relative_path}"
  hash_path="${REPO_ROOT}/hash/${module}/${HASH_FILE_NAME}"

  if [[ ! -f "${source_path}" ]]; then
    printf 'error: source file not found: %s\n' "${relative_path}" >&2
    exit 1
  fi

  digest="$(sha256_file "${source_path}")"
  mkdir -p -- "$(dirname -- "${hash_path}")"
  printf '%s  %s\n' "${digest}" "${relative_path}" >"${hash_path}"
  printf '%-22s %s\n' "${module}" "${digest}"
done
