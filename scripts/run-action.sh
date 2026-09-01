#!/usr/bin/env bash
set -euo pipefail

mode="${MENDPACT_MODE:-scan}"
target="${MENDPACT_TARGET:-}"
output="${MENDPACT_OUTPUT:-mendpact-report.json}"
policy="${MENDPACT_POLICY:-}"
auth_token_env="${MENDPACT_AUTH_TOKEN_ENV:-}"
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

validate_boolean() {
  local value="$1"
  local flag="$2"
  case "${value}" in
    true|false) ;;
    *)
      echo "MendPact Action: ${flag} must be 'true' or 'false'." >&2
      exit 2
      ;;
  esac
}

append_boolean_flag() {
  local value="$1"
  local flag="$2"
  if [[ "${value}" == "true" ]]; then
    command_args+=("${flag}")
  fi
}

validate_boolean "${allow_private}" --allow-private
validate_boolean "${allow_insecure_http}" --allow-insecure-http
if [[ -n "${policy}" ]] && \
   [[ "${allow_private}" == "true" || "${allow_insecure_http}" == "true" ]]; then
  echo "MendPact Action: policy cannot be combined with target allowance inputs." >&2
  exit 2
fi
if [[ -n "${policy}" && -n "${auth_token_env}" ]]; then
  echo "MendPact Action: policy cannot be combined with auth-token-env." >&2
  exit 2
fi
if [[ "${mode}" == "auth" && -n "${auth_token_env}" ]]; then
  echo "MendPact Action: auth mode never loads a token; remove auth-token-env." >&2
  exit 2
fi

case "${mode}" in
  auth)
    command_args=(
      mendpact auth-check "${target}"
    )
    if [[ -z "${policy}" ]]; then
      command_args+=(--fail-on "${MENDPACT_FAIL_ON:-high}")
    fi
    command_args+=(--output "${output}")
    ;;
  scan)
    command_args=(
      mendpact scan "${target}"
    )
    if [[ -z "${policy}" ]]; then
      command_args+=(--fail-on "${MENDPACT_FAIL_ON:-high}")
    fi
    command_args+=(--output "${output}")
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
    )
    if [[ -z "${policy}" ]]; then
      command_args+=(
        --scan-fail-on "${MENDPACT_SCAN_FAIL_ON:-high}"
        --contract-fail-on "${MENDPACT_CONTRACT_FAIL_ON:-breaking}"
      )
    fi
    command_args+=(--output "${output}")
    if [[ -n "${scenario}" ]]; then
      command_args+=(--scenario "${scenario}" --replay "${replay}")
    fi
    if [[ -n "${MENDPACT_SAVE_SCAN:-}" ]]; then
      command_args+=(--save-scan "${MENDPACT_SAVE_SCAN}")
    fi
    ;;
  *)
    echo "MendPact Action: mode must be 'auth', 'scan', or 'guard'." >&2
    exit 2
    ;;
esac

if [[ -n "${policy}" ]]; then
  command_args+=(--policy "${policy}")
else
  if [[ -n "${auth_token_env}" ]]; then
    command_args+=(--auth-token-env "${auth_token_env}")
  fi
  append_boolean_flag "${allow_private}" --allow-private
  append_boolean_flag "${allow_insecure_http}" --allow-insecure-http
fi

exec "${command_args[@]}"
