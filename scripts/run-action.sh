#!/usr/bin/env bash
set -euo pipefail

mode="${MENDPACT_MODE:-scan}"
target="${MENDPACT_TARGET:-}"
output="${MENDPACT_OUTPUT:-mendpact-report.json}"
allow_private="${MENDPACT_ALLOW_PRIVATE:-false}"
allow_insecure_http="${MENDPACT_ALLOW_INSECURE_HTTP:-false}"

if [[ -z "${target}" ]]; then
  echo "MendPact Action: target is required." >&2
  exit 2
fi
if [[ -z "${output}" ]]; then
  echo "MendPact Action: output cannot be empty." >&2
  exit 2
fi

append_boolean_flag() {
  local value="$1"
  local flag="$2"
  case "${value}" in
    true) command_args+=("${flag}") ;;
    false) ;;
    *)
      echo "MendPact Action: ${flag} must be 'true' or 'false'." >&2
      exit 2
      ;;
  esac
}

case "${mode}" in
  scan)
    command_args=(
      mendpact scan "${target}"
      --fail-on "${MENDPACT_FAIL_ON:-high}"
      --output "${output}"
    )
    ;;
  guard)
    baseline="${MENDPACT_BASELINE:-}"
    scenario="${MENDPACT_SCENARIO:-}"
    replay="${MENDPACT_REPLAY:-}"
    if [[ -z "${baseline}" ]]; then
      echo "MendPact Action: baseline is required in guard mode." >&2
      exit 2
    fi
    if [[ -n "${scenario}" && -z "${replay}" ]] || \
       [[ -z "${scenario}" && -n "${replay}" ]]; then
      echo "MendPact Action: scenario and replay must be supplied together." >&2
      exit 2
    fi
    command_args=(
      mendpact guard "${target}"
      --baseline "${baseline}"
      --repetitions "${MENDPACT_REPETITIONS:-1}"
      --scan-fail-on "${MENDPACT_SCAN_FAIL_ON:-high}"
      --contract-fail-on "${MENDPACT_CONTRACT_FAIL_ON:-breaking}"
      --output "${output}"
    )
    if [[ -n "${scenario}" ]]; then
      command_args+=(--scenario "${scenario}" --replay "${replay}")
    fi
    if [[ -n "${MENDPACT_SAVE_SCAN:-}" ]]; then
      command_args+=(--save-scan "${MENDPACT_SAVE_SCAN}")
    fi
    ;;
  *)
    echo "MendPact Action: mode must be 'scan' or 'guard'." >&2
    exit 2
    ;;
esac

append_boolean_flag "${allow_private}" --allow-private
append_boolean_flag "${allow_insecure_http}" --allow-insecure-http

exec "${command_args[@]}"
