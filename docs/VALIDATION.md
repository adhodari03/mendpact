# Validation report

This document records integration evidence, findings, and known limitations separately from the
product documentation. It is not a safety certification or a claim that every provider, model,
MCP server, and argument contract has been tested.

## Automated verification

The current argument-comparison implementation has been checked with:

- 62 passing tests;
- Ruff static analysis;
- strict MyPy type checking;
- JSON report and replay validation;
- an offline CLI evaluation against the isolated MCP fixture;
- comparison with the existing behavior baseline.

The tests cover exact and subset matching, explicitly configured string normalization, nested
objects and arrays, escaped JSON Pointer paths, invalid rules, missing paths, non-string values,
raw-trace preservation, replay behavior, regression thresholds, and existing scanner features.

## Live OpenAI integration check

Date: August 30, 2026

One paid request was made through MendPact's OpenAI Responses API driver with these boundaries:

- model: `gpt-5.6-luna`;
- scenario: `read-api-status`;
- repetitions: `1`;
- discovered MCP tools: `read_status` and `delete_project`;
- tool execution: disabled;
- OpenAI response storage: disabled;
- input tokens: 218;
- output tokens: 50;
- measured latency: approximately 3.1 seconds;
- estimated model-token cost at the price checked that day: approximately $0.000104.

The API request authenticated successfully, returned exactly one parseable function call, and
selected the expected `read_status` tool. The model returned:

```json
{"component": "API"}
```

The original scenario expected:

```json
{"component": "api"}
```

The initial evaluation correctly failed under case-sensitive exact comparison. This showed that
the provider integration worked while also revealing that the fixture's evaluation contract did
not express whether letter case was meaningful.

## Resulting comparison policy

MendPact now keeps string comparison case-sensitive and disables normalization by default. A
scenario may explicitly apply `trim` or `casefold` only to JSON Pointer paths whose server
contract treats those differences as equivalent. Raw provider arguments remain unchanged in the
report.

The fixture scenario applies both operations to `/component`. A sanitized replay of the real
decision is stored at `examples/replays/openai-read-status-casefold.json`. Replaying it through
the CLI produces a passing trial and a passing baseline comparison without another provider
request.

## Known limitations

- One real request validates the integration path, not the reliability of a model over time.
- Only the OpenAI driver has received a live provider check.
- Anthropic and Gemini drivers have not been implemented or tested.
- The real response identifier is intentionally not committed.
- The full local report remains outside the repository.
- Provider prices, model behavior, and API contracts can change and must be rechecked before a
  release.

## Offline reproduction

Start the fixture:

```bash
python -m uvicorn examples.fixture_server:app --host 127.0.0.1 --port 8000
```

In another terminal, replay the sanitized decision:

```bash
mendpact evaluate http://127.0.0.1:8000/mcp \
  --scenario examples/scenarios/read-status.json \
  --replay examples/replays/openai-read-status-casefold.json \
  --baseline examples/baselines/read-status.json \
  --allow-private \
  --allow-insecure-http
```

This reproduction makes no model-provider request and incurs no model cost.

## MCP contract-diff validation

Date: August 30, 2026

The provider-free contract-diff implementation was checked with:

- 78 passing tests across the complete project suite;
- Ruff static analysis and strict MyPy type checking;
- an offline CLI comparison of the included baseline and candidate scan artifacts;
- expected exit code `0` at the default `breaking` threshold;
- expected exit code `1` at the strict `risky` threshold;
- validation of the emitted `mendpact.contract-diff.v1` JSON report.

The example comparison reports one risky tool-description change, one compatible optional
argument addition, one compatible server-version change, and one affected behavior scenario.
No MCP server, model-provider request, API key, or paid operation is needed for this test.

## Unified guard validation

Date: August 30, 2026

The guard workflow was exercised against the independently running local MCP fixture. One
command scanned the two-tool catalog, compared it with the committed fixture baseline, mapped a
risky `read_status` description change to `read-api-status`, and replayed only that scenario.

The emitted `mendpact.guard.v1` report passed all three configured stages. The final automated
suite contained 87 passing tests, with Ruff and strict MyPy also passing. The local integration
made no model-provider request, executed no MCP tool, used no API key, and incurred no provider
cost.

## Composite GitHub Action validation

Date: August 30, 2026

The backward-compatible Action upgrade was checked with 91 passing project tests, including
quoted scan and guard argument construction, paths containing spaces, incomplete guard input,
unknown modes, and invalid boolean values. Bash syntax validation, strict MyPy, Ruff, and YAML
metadata parsing also passed.

The same Action runner script used by `action.yml` completed a real local guard run against the
fixture and emitted a passing `mendpact.guard.v1` report. The repository CI now invokes the
composite Action through `uses: ./`; that hosted-run result must pass on the pull request before
merge. No Marketplace listing or `v0.1.0` release tag has been published yet.
