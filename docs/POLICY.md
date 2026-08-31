# Policy as code

MendPact policies keep CI thresholds and target-network allowances in a reviewed TOML file. The
policy is resolved before any connection is attempted, embedded in JSON reports, and displayed in
the GitHub job summary.

## Production policy

```toml
schema_version = "mendpact.policy.v1"
name = "production"
profile = "production"

scan_fail_on = "high"
contract_fail_on = "risky"
allow_private = false
allow_insecure_http = false
```

The production profile cannot be weakened below `high` scan findings or `risky` contract changes.
It always rejects private targets and plaintext HTTP. Stricter thresholds remain valid.

Run a scan with the policy:

```bash
mendpact scan https://api.example/mcp \
  --policy examples/policies/production.toml \
  --output scan-report.json
```

Run the unified guard:

```bash
mendpact guard https://api.example/mcp \
  --baseline mendpact/baseline-scan.json \
  --scenario mendpact/scenarios.json \
  --replay mendpact/replay.json \
  --policy mendpact.toml \
  --output mendpact-guard-report.json
```

Policy-controlled CLI flags cannot be supplied together with `--policy`. This avoids silently
overriding a reviewed policy at run time.

## Local policy

The local profile keeps the same secure network defaults. Loopback/private targets and plaintext
HTTP must still be enabled explicitly:

```toml
schema_version = "mendpact.policy.v1"
name = "local-development"
profile = "local"

scan_fail_on = "high"
contract_fail_on = "risky"
allow_private = true
allow_insecure_http = true
```

Never reuse a local policy for a production target.

## GitHub Action

From the release containing policy support, the policy file owns the threshold and target
allowance inputs:

```yaml
- id: mendpact
  uses: adhodari03/mendpact@v0.3.0
  with:
    mode: guard
    target: https://api.example/mcp
    baseline: mendpact/baseline-scan.json
    scenario: mendpact/scenarios.json
    replay: mendpact/replay.json
    policy: mendpact.toml
    output: mendpact-guard-report.json
```

Do not combine `policy` with `allow-private` or `allow-insecure-http`. Threshold inputs are ignored
when a policy is present because the reviewed file is the source of truth.

## Exit behavior

- Exit `0`: every stage passed under the resolved policy.
- Exit `1`: findings or contract changes reached the policy threshold, or behavior failed.
- Exit `2`: the policy, target, inputs, connection, or report could not be configured.

Reports retain the policy name, profile, resolved thresholds, network allowances, and SHA-256
digest so results can be tied back to the exact reviewed file.
