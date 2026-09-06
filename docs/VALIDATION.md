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
- Anthropic and Gemini drivers are implemented and covered by mocked SDK-contract tests, but they
  have not received a live provider check.
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

## Offline model comparison validation

Date: September 2, 2026

The provider-neutral model comparison was checked with the complete 188-test project suite, Ruff,
strict MyPy, and diff whitespace validation. Tests cover matching runs, provider-resolved model
identity, token and latency snapshots, overall regression, per-scenario regression that aggregate
scores would hide, multiple independent candidates, new confusion pairs, explicit warning policy,
tampered summaries, contradictory attempts and grades, incomparable targets, duplicate run IDs,
JSON output, CI exit codes, and output/input overwrite protection.

The CLI path was exercised through its test runner using complete `mendpact.behavior.v1` artifacts.
It produced a `mendpact.model-comparison.v1` artifact and returned exit `1` for a deliberately
regressed candidate while retaining all findings. No MCP connection, tool execution, model
provider, API key, or paid request was used.

## Model comparison GitHub Action validation

Date: September 3, 2026

The `compare-models` Action mode was checked with the complete 192-test project suite, Ruff, strict
MyPy, Bash syntax validation, Action/workflow YAML parsing, and diff whitespace validation. Tests
cover shell argument construction with spaces, required reference and candidate paths, rejection
of target-dependent inputs, model-matrix job summaries, pass-rate deltas, findings, and bounded
annotations.

An offline shell smoke exercised `scripts/run-action.sh`, the real `mendpact compare-models` CLI,
the committed reference and candidate behavior fixtures, JSON report generation, and
`mendpact.action_report`. The resulting report passed and the rendered job summary identified both
models. No MCP endpoint, model provider, API key, bearer token, tool execution, or paid request was
used.

## Semantic-grader calibration validation

Date: September 3, 2026

The offline semantic-score calibration layer was checked with the complete 206-test project
suite, Ruff, strict MyPy, Bash syntax validation, Action/workflow YAML parsing, and diff whitespace
validation. Tests cover calibration-only threshold selection, validation-split isolation,
safety-oriented tie breaking, confusion metrics, false-accept and balanced-accuracy policy,
minimum split sizes, label diversity, duplicate IDs, formatting-independent dataset digests, CLI
exit codes, output overwrite protection, Action argument construction, and job-summary rendering.

A local CLI and Action-shell smoke used the committed eight-example fixture. Both paths selected
threshold `0.820`, produced a passing `mendpact.semantic-calibration.v1` report, and measured the
four-example validation split without a false accept. The Action renderer produced the expected
semantic-calibration job summary.

The fixture proves the mechanics and is deliberately labelled as an example, not as a production
benchmark. MendPact consumed already-saved semantic scores; it did not generate those scores,
contact a model provider or MCP endpoint, load a credential, execute a tool, or incur a paid
operation.

## Unified reliability policy v2 validation

Date: September 3, 2026

Policy v2 was checked with the complete 225-test project suite, Ruff, strict MyPy, Bash syntax
validation, Action/workflow YAML parsing, and diff whitespace validation. Tests cover v1 backward
compatibility, rejection of v2-only sections under a v1 schema, resolved local and production
defaults, explicit nested gates, production safety ceilings, CLI policy/option conflicts, policy
file overwrite protection, Action argument construction, embedded policy evidence, and GitHub job
summary rendering.

Offline CLI and Action-shell smoke runs applied the committed local v2 fixture to both model
comparison and semantic calibration. All four paths passed, retained the v2 policy identity and
source digest in their JSON reports, and rendered the applied policy in their summaries. The
project initializer and committed production example now generate the reviewed v2 sections.

No MCP endpoint, model provider, credential, tool execution, network request, or paid operation was
used. The local fixture is explicitly test-only. Production parsing independently enforces the
documented model-regression, confusion, sample-size, balanced-accuracy, and false-accept limits.

## Privacy-minimized evidence export validation

Date: September 5, 2026

The first hosted-beta preparation slice adds an offline exporter, not a hosted service. The full
local suite passed 293 tests, including 37 evidence-export tests. Ruff, strict MyPy, CI YAML
parsing, and diff whitespace validation passed. The export module reached 98% statement coverage
in its focused test run. These results are local; the new GitHub workflow steps have not yet run
remotely.

Tests cover explicit source versions and headers, duplicate/non-finite JSON rejection, bounded
regular-file input, symlink and FIFO refusal, safe no-overwrite output, HTML escaping, restrictive
CSP, network-denied export, source-byte SHA-256, source-text sentinel omission, failed/error/skipped
outcomes, guard stage consistency, and CLI exit semantics. Provider-labelled test fixtures are
not evidence of a live provider request.

Local CLI smoke checks exported the committed scan and replay behavior fixtures to HTML and
versioned summary JSON. An independently running MCP fixture on loopback port 8769 was scanned
under the deliberately permissive critical threshold and then guarded under the local strict
policy. The guard correctly returned exit code 1 for its high-severity finding. Both evidence
exports returned exit code 0 while retaining recorded status `failed`, scan `failed`, contract
`passed`, and behavior `skipped` (no contract change affected a scenario). The temporary fixture
server was stopped after verification.

The generated scan and guard HTML were inspected in the browser. Desktop stage cards were
readable, and a 375-pixel viewport check found no horizontal overflow. Sample outputs live under
the ignored `reports/` directory; no source or summary was published to GitHub Pages.

No credentials were loaded, model providers called, or MCP tools executed. Only local fixture
discovery used networking. This validates export mechanics and basic evidence consistency, not
report authenticity, a cryptographic attestation, production safety, or a hosted deployment.

## Local run history validation

Date: September 6, 2026

The local history slice was implemented on `feat/local-run-history` after the evidence-export
PR was merged. The complete local suite passed 329 tests, including 35 new history tests, with
resource warnings treated as errors. Ruff, strict MyPy, CI YAML parsing, and diff whitespace
validation passed. Focused statement coverage was 98% for the history storage/comparison module
and 84% for its CLI (94% combined). These are local results; the added CI smoke step has not yet
run on GitHub.

Tests exercise exact-file deduplication without extending import age, sensitive-text omission,
private-file permissions, source preservation, safe path rejection, read-only pagination,
unknown/corrupt store rejection, concurrent duplicate imports into an initialized database,
target/type mismatch rejection, policy/model/setup warnings, skipped/error-stage handling,
source-time ordering, output overwrite protection, and preview/apply cleanup at the exact
14-day import-age boundary. Network connections were blocked in an offline workflow test.

A local CLI smoke imported the two committed contract-scan fixtures, reimported the first to
verify deduplication, listed two entries, produced a versioned comparison JSON, and previewed
cleanup. The freshly imported entries were not eligible for deletion. Their equal scan counts
produced zero count deltas; this is explicitly not a claim that their contracts are identical.
The SQLite database and comparison remain in an ignored local reports directory.
SQLite sidecar ignore rules were also checked.

The shared report loader and no-overwrite artifact writer were reused without changing the
existing export command's interface. Review identified a numeric edge case: JSON exponents such
as `1e999` can parse to infinity without using a literal `Infinity` token. The shared loader now
rejects this form too, with an additional regression test. Test-owned SQLite connections were
also closed explicitly to eliminate resource warnings.

No model provider or MCP endpoint was contacted, no credential was loaded, no original report
was deleted, and no data was published. Actual pruning was exercised only on test-owned temporary
databases. History contains minimized local evidence, not encrypted storage or authenticated
attestations; its comparisons are descriptive and do not replace reliability gates. The explicit
14-day cleanup command is implemented, but no background cleanup or hosted service was enabled.

## Reviewed sharing package validation

Date: September 6, 2026

This slice was implemented on `feat/reviewed-sharing-packages`, starting from the committed local
history feature. At branch creation, the history commit was pushed but had not yet appeared in
`origin/main`; merge the history PR before this dependent feature PR.

The complete local suite passed 378 tests, including 49 sharing-package tests, with resource
warnings treated as errors. Ruff, strict MyPy, CI YAML parsing, and diff whitespace validation
passed. Focused statement coverage was 97% for sharing logic and 85% for the CLI (94% combined).
The new GitHub smoke step has not yet run remotely.

Tests cover deterministic fixed-content ZIPs, source-text omission, all supported report types,
full guard-stage packages, unchanged source/output files, explicit acknowledgement, exact
package-digest binding, receipt lifetime and expiry boundaries, malformed receipts, duplicate
JSON keys, and rejection of compressed, symlink, duplicate, unexpected, traversal, altered, and
trailing-content archive inputs. Inspection checks content without extracting it. Arbitrary
summary text and HTML changes are rejected even when an artifact digest is recomputed. A
network-denied test exercises the complete CLI workflow on synthetic data.

Additional testing found that a literal-boolean model field could accept numeric `1` as `true`.
Verification now checks the raw JSON acknowledgement is the boolean `true`, with regression
tests for numeric and string substitutes. This is a format check, not proof of human consent.

A local CLI smoke prepared and inspected the committed candidate-scan fixture; both commands
returned the same package fingerprint. The generated ZIP remains in an ignored local reports
directory and was neither approved nor published. Acknowledgement and verification were exercised
only with test-owned synthetic fixtures. No production approval receipt was created.

The shared atomic no-overwrite writer now supports bytes so ZIP output uses the same protections
as text evidence. Existing evidence-export and history tests continue to pass. No provider API,
MCP endpoint, credential, hosting account, GitHub Pages deployment, or external upload was used.

Successful verification only establishes matching package bytes and an unexpired unsigned local
acknowledgement. It does not authenticate the reviewer, establish source freshness, certify
safety, or recall previously shared copies. An authenticated publisher, remote revocation,
hosted deletion, and signed attestations remain unimplemented.

## Real-world validation setup

Date: September 6, 2026

The real-world validation preparation slice is implemented on `feat/real-world-validation-setup`.
It does not contact external MCP servers, load environment-variable values, execute MCP tools, or
call model providers. `scripts/prepare_validation.py` creates a fresh mode-700 workspace under
the ignored `reports/validation/` directory with strict production and loopback policies, a
review template, an allowlisted environment manifest, and a 14-day manual cleanup reminder.
Existing workspaces are never overwritten. The manifest records preparation provenance only; it
is not a signed attestation or a claim that a scan ran.

The playbook in `docs/REAL_WORLD_VALIDATION.md` defines authorized target selection, a bounded
two-scan discovery budget, strict exit-code interpretation, offline diff/export/history analysis,
finding triage, and disclosure/cleanup boundaries. It explicitly treats public accessibility as
insufficient permission, keeps unsupported transports as coverage gaps, and separates confirmed
concerns from suspected false positives and unknowns. The review template requires an exact
upstream revision and permission record while prohibiting tokens, headers, customer data, and
unreviewed raw artifacts from issues or public pages.

Validation of the setup itself passed in the complete local suite (393 tests), Ruff, strict MyPy,
and the CI YAML checks. The offline setup smoke test uses committed fixtures only and asserts that
no scan artifact is created. External target validation is intentionally pending the next work
session and target-owner authorization. No pass percentage or security certification is claimed.
