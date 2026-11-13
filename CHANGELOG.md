# Changelog

MendPact follows semantic versioning for its CLI and published GitHub Action. The project remains
an open-source alpha; release numbers describe interface evolution rather than a safety
certification.

## 0.3.0 — 2026-11-13

### Added

- Official MCP Registry discovery, exact server inspection, and explicit endpoint selection.
- Provenance-bound registry candidates and private draft validation workspaces.
- Policy-as-code, bounded waivers, secure repository initialization, and OAuth metadata checks.
- Offline model-run comparison, semantic-grader calibration, and Anthropic and Gemini drivers.
- Privacy-minimized evidence exports, local run history, reviewed sharing packages, and static
  evidence-site preparation.
- Offline single and batch scan rechecks with rule-impact deltas.
- Authorization-gated validation sessions with preflight, a two-scan limit, and minimized
  summaries.
- Public GitHub Pages documentation and validation records from three independently developed
  open-source MCP implementations.

### Changed

- Consequential-action checks now combine tool-name and description context more carefully.
- Nested MCP connection failures now surface bounded, actionable leaf errors.
- The composite GitHub Action supports policy, authentication preflight, evaluation, model
  comparison, semantic calibration, and scan recheck modes.

### Security boundaries

- Discovery and candidate preparation never install registry packages or contact advertised MCP
  endpoints.
- Behavioral evaluation selects and grades tools but never executes them.
- Registry publication, HTTPS, a passing report, and exported evidence do not certify safety or
  authorize testing.

## 0.2.0 — 2026-08-27

- Added the unified guard workflow, contract baselines, PR summaries, bounded annotations, and
  release-smoke validation for the composite GitHub Action.

## 0.1.0 — 2026-08-27

- Released the deterministic Streamable HTTP MCP scanner, capability graph, initial metadata
  checks, JSON reports, CLI exit codes, and first composite GitHub Action.
