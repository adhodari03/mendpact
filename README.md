# MendPact

MendPact is a protocol-native reliability scanner for AI agents. The first release connects to
a remote Model Context Protocol (MCP) endpoint, inventories its capabilities, builds a graph of
the exposed surface, runs deterministic safety checks, and emits a CI-friendly report.

> **Status:** early development. MendPact reports observable risks and compatibility signals;
> it does not certify that an agent is safe.

## Why start here?

Remote MCP discovery gives maintainers value without asking them to install an SDK in their
application or give MendPact source-code access. The deterministic core also provides a stable
baseline before probabilistic, model-driven evaluations are added.

## Quick start

MendPact requires Python 3.12 or newer.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
mendpact scan https://example.com/mcp --output report.json
```

Local endpoints are blocked by default. To scan a development server deliberately:

```bash
python -m uvicorn examples.fixture_server:app --host 127.0.0.1 --port 8000

mendpact scan http://127.0.0.1:8000/mcp \
  --allow-private \
  --allow-insecure-http \
  --output report.json
```

The fixture intentionally exposes a destructive-looking tool, so this scan exits with code `1`
and demonstrates the CI failure path.

## Behavioral evaluation

MendPact can also test whether a model decision chose the intended MCP tool and produced valid
arguments. Replay mode is deterministic and free to run, while the optional OpenAI driver asks a
live model to select a tool through the Responses API. Neither mode executes the selected tool.

With the fixture server running, evaluate the included scenario and recorded decision:

```bash
mendpact evaluate http://127.0.0.1:8000/mcp \
  --scenario examples/scenarios/read-status.json \
  --replay examples/replays/read-status.json \
  --allow-private \
  --allow-insecure-http \
  --output behavior-report.json
```

A scenario states a natural-language task, the expected tool and arguments, and any forbidden
tools. MendPact checks the replayed choice against the discovered tool catalog, validates its
arguments with the tool's JSON Schema, and reports repeated wrong-tool choices as confusion
edges. The provider-neutral trace format supports OpenAI now and additional model drivers later.
A full report records the selected tool, arguments, resolved model, response ID,
latency, and token counts without storing the API key or raw provider response.

String comparison remains case-sensitive, and normalization is disabled by default. A scenario
can explicitly normalize only string fields whose server contract treats formatting or letter
case as equivalent. Exact versus subset comparison remains controlled by `argument_match`.
Paths use JSON Pointer syntax, and raw model arguments remain unchanged in reports:

```json
"argument_normalization": {
  "/component": ["trim", "casefold"]
}
```

### Live OpenAI evaluation

Install the optional SDK and set the API key in your environment:

```bash
python -m pip install -e '.[openai]'
export OPENAI_API_KEY='your-key'
```

Then run the same scenario with an explicit model. This makes a paid API request but still does
not execute any MCP tool:

```bash
mendpact evaluate http://127.0.0.1:8000/mcp \
  --scenario examples/scenarios/read-status.json \
  --driver openai \
  --model gpt-5.6-luna \
  --allow-private \
  --allow-insecure-http \
  --output behavior-report.json \
  --save-replay replay.json
```

The saved replay file can reproduce the decisions later without another model call. MendPact
uses function definitions and single-call controls described in the
[official OpenAI function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).

### Regression baselines

Save a reviewed behavior run as the expected result for later changes:

```bash
mendpact evaluate http://127.0.0.1:8000/mcp \
  --scenario examples/scenarios/read-status.json \
  --replay examples/replays/read-status.json \
  --allow-private \
  --allow-insecure-http \
  --save-baseline behavior-baseline.json \
  --min-pass-rate 0.95 \
  --max-pass-rate-drop 0.02
```

Then compare every candidate change with that versioned baseline:

```bash
mendpact evaluate http://127.0.0.1:8000/mcp \
  --scenario examples/scenarios/read-status.json \
  --replay examples/replays/read-status.json \
  --baseline behavior-baseline.json \
  --allow-private \
  --allow-insecure-http \
  --output behavior-report.json
```

The baseline stores the scenario set, sample size, pass rate, failed-trial allowance, known
wrong-tool confusions, driver, model, and CI thresholds. A comparison fails when quality drops
beyond policy or the sample is no longer comparable. Driver and model changes are visible
warnings by default because testing a new model is a normal use case. The report also includes
a one-sided proportion-test p-value as supporting statistical context; predictable thresholds
remain the source of the CI exit code. See the included
[`read-status` baseline](examples/baselines/read-status.json) for the JSON format.

## MCP contract diff

MendPact can compare two versioned scan reports without reconnecting to either MCP server. It
classifies capability and JSON Schema changes as `compatible`, `risky`, or `breaking`, then maps
changed tools to behavior scenarios that may need retesting.

```bash
mendpact diff \
  examples/contracts/baseline-scan.json \
  examples/contracts/candidate-scan.json \
  --scenario examples/scenarios/read-status.json \
  --fail-on risky \
  --output contract-diff.json
```

The default CI threshold is `breaking`. Use `--fail-on risky` when description changes, newly
added tools, relaxed schemas, or other model-routing risks should also block a change. Reports
include stable rule IDs, before-and-after evidence, JSON Pointer paths, and affected scenario
IDs. The example intentionally exits with code `1` under the strict `risky` threshold because
the tool description changed. The command is deterministic and makes no model-provider or MCP
network request. See the [contract-diff rule reference](docs/CONTRACT_DIFF.md) for the complete
classification policy.

## Unified CI guard

`mendpact guard` combines the routine pull-request workflow into one command. It scans the
current endpoint once, compares it with a committed contract baseline, calculates the behavior
blast radius, and replays only affected scenarios against the discovered tool catalog.

```bash
mendpact guard http://127.0.0.1:8000/mcp \
  --baseline examples/guard/baseline-scan.json \
  --scenario examples/scenarios/read-status.json \
  --replay examples/replays/read-status.json \
  --scan-fail-on critical \
  --allow-private \
  --allow-insecure-http \
  --output guard-report.json
```

The resulting `mendpact.guard.v1` report embeds scan, contract, and replay evidence under one CI
status. The workflow does not execute MCP tools or contact a model provider, so it is
deterministic and free to run. See the [guard reference](docs/GUARD.md) for its stage and exit-code
policy.

## GitHub Action

MendPact can run as a composite GitHub Action. Scan mode remains the default for backward
compatibility, while guard mode runs the complete scan, contract, and affected-replay workflow.

```yaml
- id: mendpact
  uses: adhodari03/mendpact@v0.2.0
  with:
    mode: guard
    target: https://your-server.example/mcp
    baseline: mendpact/baseline-scan.json
    scenario: mendpact/scenarios.json
    replay: mendpact/replay.json
    output: mendpact-guard-report.json
```

The `v0.2.0` Action writes a Markdown job summary and bounded workflow annotations while keeping
the JSON report as its complete machine-readable output. It also exposes the report and
candidate-scan paths so the consuming workflow controls artifact upload and retention. Pin an
exact full commit SHA when an immutable reference with stronger supply-chain guarantees is
required. See the [GitHub Action guide](docs/GITHUB_ACTION.md) for complete scan and guard
workflows.

## Policy as code

MendPact can load reviewed production or local settings from a versioned TOML policy. Production
policies fail on `high` scan findings and `risky` contract changes by default, and cannot enable
private targets or plaintext HTTP.

```bash
mendpact guard https://api.example/mcp \
  --baseline mendpact/baseline-scan.json \
  --policy mendpact.toml \
  --output mendpact-guard-report.json
```

The resolved policy is embedded in the report and GitHub job summary. See the
[policy reference](docs/POLICY.md) for profiles, Action configuration, and exit behavior.

## MCP conformance

MendPact also wraps the official MCP server conformance framework, pinned to version `0.1.16`.
This command requires Node.js 22 or newer because the upstream runner is distributed through npm.
The pinned release supports the `active`, `all`, and `pending` server suites.

The default runs only the initialization scenario:

```bash
mendpact conformance http://127.0.0.1:8000/mcp \
  --allow-private \
  --allow-insecure-http \
  --output conformance-report.json
```

Broader scenarios may invoke MCP tools and must only target an isolated test server. MendPact
requires an explicit acknowledgement:

```bash
mendpact conformance http://127.0.0.1:8000/mcp \
  --suite active \
  --allow-tool-calls \
  --allow-private \
  --allow-insecure-http
```

The wrapper uses the upstream exit code, retains the runner output, and normalizes every
`checks.json` artifact into a versioned MendPact conformance report. The upstream framework is
still marked unstable, which is why MendPact pins rather than silently following its latest
release.

Exit codes are designed for CI:

- `0`: the command completed and all configured checks passed;
- `1`: the command completed and a scan, conformance check, or behavior trial failed;
- `2`: validation, discovery, setup, replay data, or report writing failed.

## Current checks

- missing or weak tool descriptions;
- schemas that accept arbitrary arguments;
- names and descriptions suggesting mutating, destructive, credential, execution, or financial
  behavior;
- tool descriptions containing prompt-injection-like instructions;
- overly large tool catalogs;
- insecure HTTP transport.

These checks are intentionally conservative heuristics. Every finding includes its rule ID and
evidence so a maintainer can review it rather than accepting a mysterious score.

## Development

```bash
python -m ruff check .
python -m mypy src
python -m pytest
```

CI also starts the isolated fixture and runs the pinned `server-initialize` conformance scenario.
The normalized conformance JSON is uploaded as a workflow artifact.

See [the architecture](docs/ARCHITECTURE.md), [security boundary](docs/SECURITY.md), and
[roadmap](docs/ROADMAP.md) for the technical direction. The [cost guide](docs/COSTS.md) explains
how to keep routine evaluation free and reserve small paid runs for provider validation.
Completed integration checks and their limitations are recorded in the
[validation report](docs/VALIDATION.md).

## License

MendPact is licensed under the [Apache License 2.0](LICENSE).
