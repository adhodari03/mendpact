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
fixture and emitted a passing `mendpact.guard.v1` report. The repository CI invokes the composite
Action through `uses: ./`, and that hosted run passed before merge.

The immutable `v0.1.0` GitHub release was published and then exercised through
`adhodari03/mendpact@v0.1.0` by the dedicated release-smoke workflow on August 31, 2026. The
published Action completed guard mode successfully and produced the expected JSON artifact. This
validated the public release reference without contacting a model provider or executing an MCP
tool.

## PR-native GitHub feedback validation

Date: August 31, 2026

The `v0.2.0` implementation renders scan and guard JSON into GitHub job summaries and bounded
annotations. Untrusted report values and workflow-command characters are escaped, target URL
credentials and query parameters are omitted, and presentation failures cannot change the
underlying MendPact result.

The implementation passed 95 project tests, Ruff, strict MyPy, YAML parsing, and a provider-free
local guard run through the Action shell path. That run passed its scan, contract, and affected
behavior stages, then rendered the stage table, one risky contract change, affected scenario,
and deterministic scan findings into the expected summary.

## Project initialization validation

Date: September 1, 2026

The production initializer was checked with the complete 127-test project suite, Ruff, strict
MyPy, and an isolated CLI smoke run. The smoke run generated a production policy, GitHub workflow,
labeled example scenario, and empty baseline directory without contacting an MCP server or model
provider. The generated workflow parsed as YAML and the scenario parsed as JSON.

Tests cover deterministic output, collision refusal before any file is written, explicit `--force`
replacement limited to generated paths, preservation of unrelated files, and rejection of HTTP,
embedded credentials, query strings, fragments, malformed ports, and whitespace. The initializer
also rejects structural collisions and symlinks before writing. It does not fabricate a trusted
baseline or silently enable guard mode.

## Authenticated-target validation

Date: September 1, 2026

Bearer transport and OAuth metadata inspection were checked with the complete 148-test project
suite, Ruff, strict MyPy, Bash syntax validation, and Action metadata YAML parsing. Mocked HTTP
tests cover Bearer challenge discovery, path-specific then root protected-resource fallback,
exact resource and issuer matching, OAuth and OpenID metadata discovery, required HTTPS endpoints,
PKCE `S256` signaling, missing metadata, policy resolution, GitHub Action argument construction,
and report rendering.

A local network integration wrapped the two-tool MCP fixture with an HTTP authorization boundary
that returned `401` unless every request contained the expected Bearer header. Both the transport
adapter and a complete CLI scan discovered the two tools only when configured with the disposable
environment-loaded credential, proving the header reached the real MCP transport rather than only
a mocked function. The CLI report retained the environment-variable name and expected local OAuth
findings without containing the token value. No credential was written to the repository.

No third-party MCP server, production credential, OAuth login, model-provider request, or paid
operation was used. Full authorization-code, refresh-token, audience-claim, and live hosted-server
interoperability remain outside this implementation; MendPact consumes a pre-issued token and
audits discovery metadata without acquiring credentials.

## Credential-free authorization preflight validation

Date: September 1, 2026

The standalone `auth-check` command and GitHub Action `auth` mode were checked with the complete
161-test project suite, Ruff, strict MyPy, Bash syntax validation, Action/example YAML parsing, and
diff whitespace validation. Tests cover a valid credential-free discovery chain, absence of an
`Authorization` header on every metadata request, severity thresholds, exact active waivers,
target-validation errors, versioned JSON output, policy-owned settings, an unset policy-named
token variable, Action argument construction, accidental token-input rejection, and GitHub summary
rendering.

An isolated loopback smoke run exercised both the installed CLI and the actual Action shell path
against the local MCP fixture. The fixture intentionally has no RFC 9728 metadata and uses HTTP,
so both paths produced the expected `mendpact.authorization.v1` failure report, returned exit `1`,
and reported `MP-AUTH-001`/`MP-AUTH-002` instead of falsely passing. The generated report recorded
`credential_source: none` and a null `bearer_token_env`; its GitHub summary and annotations were
also rendered successfully.

The passing metadata path was exercised with an in-memory HTTP transport and realistic Bearer,
protected-resource, and authorization-server documents. No third-party endpoint, bearer token,
model provider, API key, or paid request was used. Live interoperability with a deployed HTTPS MCP
authorization server remains a pre-release validation task.

## Contract baseline lifecycle validation

Date: September 2, 2026

The baseline inspection and promotion workflow was checked with the complete 178-test project
suite, Ruff, and strict MyPy. Tests cover formatting-independent canonical digests, capability
counts, incomplete and error scans, target/graph mismatch, non-MCP graphs, missing server identity,
duplicate node IDs, dangling edges, status/threshold consistency, exact scan-ID acknowledgement,
exact expected-target matching,
separate failed-scan acceptance, controlled replacement, missing destination directories, symlink
refusal, canonical output, and the nested CLI commands.

An offline CLI smoke used the committed Guard fixture baseline. MendPact inspected its identity,
promoted it into a temporary directory using the exact scan ID and target, then inspected the
promoted result again. The canonical digest remained identical and the two-tool MCP inventory was
preserved. No MCP connection, tool execution, model provider, API key, bearer token, or paid request
was used.
