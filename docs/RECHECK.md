# Offline scan recheck

`mendpact recheck` applies the installed MendPact version's deterministic metadata rules to a
previously saved, complete `mendpact.scan.v1` report. It is useful after rules change: maintainers
can see how a reviewed capability snapshot scores now without reconnecting to the MCP deployment.

```bash
mendpact recheck reports/original-scan.json \
  --policy mendpact.toml \
  --output reports/rechecked-scan.json
```

Without a policy file, use `--fail-on` to choose the minimum failing severity. The default is
`high`. Exit code `0` means the saved graph passes the current threshold, `1` means it fails, and
`2` means the input, configuration, or output is invalid.

## What changes

The command validates the original report, hashes its exact bytes, and runs the current
deterministic capability rules against its saved graph. Old deterministic findings are replaced,
then the current policy threshold and exact active waivers are applied. The new report retains the
original scan ID, target, graph, and capture time so it continues to identify the same snapshot.

The optional `recheck` object records:

- the original file's SHA-256;
- the recheck time and MendPact version;
- the original recorded status;
- the count of preserved authorization findings; and
- `authorization_refreshed: false`.

The output remains a `mendpact.scan.v1` report so existing diff, evidence, history, and job-summary
tools can read it. Those views label it as an offline deterministic recheck. The command creates a
new output file atomically and refuses to overwrite an existing file, including its source.

## What does not change

Recheck makes no network connection, performs no DNS lookup, sends no provider request, loads no
credential, and executes no MCP tool. It does not rediscover the deployment or refresh OAuth
metadata. Existing `MP-AUTH-*` findings stay visible but are explicitly counted as preserved,
unrefreshed evidence; current waivers are reapplied to them.

Because the graph may no longer match the deployed server, a recheck is not proof of current
production state. Run a new `mendpact scan` when endpoint freshness matters. A rechecked output
cannot be used as another recheck source, which keeps the provenance chain limited to one original
capture.

## GitHub Action

The composite Action exposes the same offline boundary:

```yaml
- uses: adhodari03/mendpact@main
  with:
    mode: recheck
    source-report: mendpact/baselines/baseline-scan.json
    policy: mendpact.toml
    output: mendpact-rechecked-scan.json
```

Use `main` only for pre-release testing and replace it with a reviewed immutable release tag or
commit SHA. Recheck mode rejects target, authentication, and target-network allowance inputs.
Artifact upload remains the consuming workflow's responsibility; use no more than 14 days of
retention for temporary reports.
