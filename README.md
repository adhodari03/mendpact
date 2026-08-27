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

- `0`: scan completed and no finding met the failure threshold;
- `1`: scan completed and at least one finding met the threshold;
- `2`: target validation, MCP discovery, conformance setup, or report writing failed.

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
[roadmap](docs/ROADMAP.md) for the technical direction.

## License

MendPact is licensed under the [Apache License 2.0](LICENSE).
