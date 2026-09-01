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

Contract intelligence compares two completed scan artifacts rather than contacting their
targets again. It matches capabilities by stable graph node ID, classifies structural and schema
changes, and joins tool changes with behavior expectations to calculate a scenario blast radius.
This makes compatibility review reproducible in pull requests and independent of model-provider
availability.

The guard orchestrator is the CI composition boundary. It scans once, feeds the resulting graph
to contract comparison, selects affected scenarios, and evaluates deterministic replays against
that same in-memory graph. The versioned guard report embeds each stage's evidence instead of
reducing the result to an opaque score.

The root composite GitHub Action is a thin distribution adapter. It validates Action inputs,
constructs quoted CLI arguments without shell evaluation, installs the referenced repository
revision, and exposes generated artifact paths to the consuming workflow. Scan remains the
default mode so existing Action configurations continue to work. Authorization mode calls the
same credential-free audit as the CLI and rejects token configuration before constructing the
command.

Authorization preflight is a separate read-only vertical slice:

```text
target validation ---> unauthenticated Bearer challenge
                                 |
                                 v
                   protected-resource metadata
                                 |
                                 v
                   authorization-server metadata
                                 |
                                 v
               versioned authorization audit report
```

The preflight shares the metadata parser and network policy used by authenticated scans, but it
does not instantiate bearer authentication or connect through the MCP client. This separation is
represented explicitly in report evidence as `credential_source: none`.

The separate `mendpact conformance` path invokes the pinned official MCP conformance CLI as a
child process. It validates the target first, runs the upstream package without a shell, reads
the emitted `checks.json` files from an ephemeral directory, and normalizes them into the
provider-neutral MendPact report schema. The npm package remains an external executable rather
than a Python dependency so its version and supply-chain boundary stay explicit.

## Boundaries

- `domain.py` owns provider-neutral, serialized data structures.
- `authorization.py` orchestrates credential-free OAuth discovery audits.
- `adapters/` converts protocol-specific objects into the domain model.
- `checks/` operates only on the normalized capability graph.
- `scanner.py` orchestrates a run and determines its CI status.
- `behavior.py` orchestrates replayable task-to-tool evaluations.
- `drivers/` converts provider decisions into normalized traces.
- `argument_matching.py` applies scenario-approved string normalization to copied arguments.
- `grading.py` validates selected tools, arguments, and behavioral expectations.
- `regression.py` creates versioned baselines and evaluates compatibility thresholds.
- `contract_diff.py` compares scan graphs and maps changes to affected behavior scenarios.
- `guard.py` composes scanning, contract comparison, and affected replay evaluation.
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
