# Roadmap

## Milestone 0.1 — deterministic MCP scanner

- [x] Streamable HTTP target validation
- [x] MCP capability discovery
- [x] normalized capability graph
- [x] deterministic tool metadata and schema checks
- [x] JSON and terminal reports
- [x] CI exit codes and composite GitHub Action
- [x] exercise the CLI against an independently running fixture server
- [x] wrap the pinned official MCP conformance runner

## Milestone 0.2 — behavioral compatibility

- [x] provider-neutral `ModelDriver` and trace models
- OpenAI Responses API driver
- [x] task-to-tool selection scenarios
- [x] JSON Schema argument grading
- repetition, baselines, and statistical regression thresholds
- [x] deterministic repetition and wrong-tool confusion summaries
- [x] trace replay without a live model call

## Milestone 0.3 — cross-provider matrix

- Anthropic and Gemini drivers
- provider and model snapshots
- semantic grading calibrated against human labels
- compatibility diff between agent versions and model versions

## Milestone 0.4 — hosted beta

- projects, authentication, and encrypted bring-your-own-key storage
- scheduled scans and GitHub checks
- PostgreSQL persistence and object storage
- versioned public reports and signed passports
- opt-in compatibility index
