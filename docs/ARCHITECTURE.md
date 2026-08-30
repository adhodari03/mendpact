# Architecture

MendPact separates protocol discovery, deterministic analysis, model drivers, grading, and
reporting. The current vertical slices cover metadata scanning, upstream conformance, and
replayable behavioral evaluation without requiring a paid model API.

```text
CLI / GitHub Action
        |
        v
target validation ---> MCP adapter ---> capability graph
                                           |
                                           v
                                  deterministic checks
                                           |
                                           v
                                JSON + terminal report
```

Behavioral evaluation reuses the same discovered capability graph:

```text
scenario suite ---> ModelDriver ---> normalized tool-call trace
                                          |
MCP adapter ---> discovered tool schemas -+-> deterministic grader
                                                   |
                                                   v
                                      behavior report + confusion edges
                                                   |
                                                   v
                                     versioned baseline comparison
```

The replay driver reads recorded choices instead of contacting a model. The OpenAI driver sends
the scenario task and normalized function schemas to the Responses API, then records the returned
choice without executing it. Both drivers emit the same trace, so the grader checks the selected
name and arguments against the discovered catalog and JSON Schema without provider-specific code.

The regression layer converts a complete behavior report into a compact baseline containing the
scenario set, sample size, quality summary, known confusion edges, provider metadata, and CI
policy. Later runs are compared without provider-specific logic. The machine report retains the
raw trial evidence, threshold findings, and a one-sided pass-rate statistic; configured
thresholds determine the exit code. A failed comparison cannot be promoted accidentally when a
baseline is loaded and saved in the same command.

The separate `mendpact conformance` path invokes the pinned official MCP conformance CLI as a
child process. It validates the target first, runs the upstream package without a shell, reads
the emitted `checks.json` files from an ephemeral directory, and normalizes them into the
provider-neutral MendPact report schema. The npm package remains an external executable rather
than a Python dependency so its version and supply-chain boundary stay explicit.

## Boundaries

- `domain.py` owns provider-neutral, serialized data structures.
- `adapters/` converts protocol-specific objects into the domain model.
- `checks/` operates only on the normalized capability graph.
- `scanner.py` orchestrates a run and determines its CI status.
- `behavior.py` orchestrates replayable task-to-tool evaluations.
- `drivers/` converts provider decisions into normalized traces.
- `grading.py` validates selected tools, arguments, and behavioral expectations.
- `regression.py` creates versioned baselines and evaluates compatibility thresholds.
- `reporting.py` renders stable machine and human interfaces.
- `security/` rejects unsafe targets before network access.
- `conformance.py` owns the pinned external runner boundary and result normalization.

The `ModelDriver` protocol is deliberately small. OpenAI's implementation uses Responses API
function calling, while future Anthropic and Google implementations will emit the same MendPact
trace model. The evaluation engine therefore remains comparable across model providers.

## Why PostgreSQL later, not a graph database now?

The in-memory Pydantic graph is sufficient for endpoint scans. The hosted product can persist
nodes and edges in PostgreSQL and use recursive CTEs for reachability, delegation loops, and
unsafe-path queries. A dedicated graph database is unnecessary until measured workloads prove
otherwise.
