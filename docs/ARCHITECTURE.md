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

The model-comparison layer consumes complete behavior reports rather than contacting providers
again. It verifies trial shape, scenario definitions, tool catalogs, provider metadata, and
recomputed summaries before allowing a comparison:

```text
reference behavior report ----+
                              +--> integrity + comparability checks --> model matrix report
candidate behavior reports ---+                                      +--> CI exit status
```

Each candidate keeps aggregate telemetry and per-scenario tool-selection distributions. Strict
overall, per-scenario, and new-confusion rules prevent an improvement in one scenario from hiding
a regression in another. The output is provider-neutral, so future drivers can participate
without changing the comparison engine.

The semantic-calibration layer consumes scores from a separately operated semantic grader and
human labels split into calibration and validation partitions:

```text
human labels + saved semantic scores
                 |
                 +--> calibration split --> threshold selection
                 |
                 +--> validation split ---> independent quality + false-accept policy
                                              |
                                              v
                                versioned calibration report + CI status
```

Validation data never participates in threshold selection. The report binds the result to the
grader name/version and a canonical dataset digest. This layer validates probabilistic grading;
it does not override deterministic tool, schema, and forbidden-action checks.

Contract intelligence compares two completed scan artifacts rather than contacting their
targets again. It matches capabilities by stable graph node ID, classifies structural and schema
changes, and joins tool changes with behavior expectations to calculate a scenario blast radius.
This makes compatibility review reproducible in pull requests and independent of model-provider
availability.

The contract baseline lifecycle separates machine capture from human trust. Inspection validates
the scan schema and graph structure and exposes a canonical digest. Promotion requires the exact
scan ID and optionally the exact deployment target, then atomically writes canonical JSON. Failed
scans and baseline replacement each require their own explicit acknowledgement.

The guard orchestrator is the CI composition boundary. It scans once, feeds the resulting graph
to contract comparison, selects affected scenarios, and evaluates deterministic replays against
that same in-memory graph. The versioned guard report embeds each stage's evidence instead of
reducing the result to an opaque score.

The root composite GitHub Action is a thin distribution adapter. It validates Action inputs,
constructs quoted CLI arguments without shell evaluation, installs the referenced repository
revision, and exposes generated artifact paths to the consuming workflow. Scan remains the
default mode so existing Action configurations continue to work. Authorization mode calls the
same credential-free audit as the CLI and rejects token configuration before constructing the
command. Model-comparison mode maps two local report paths and deterministic thresholds to the
same offline CLI engine, without requiring a target or accepting credentials. Policy v2 extends
the reviewed policy boundary to model-comparison and semantic-calibration gates while preserving
v1 behavior for scan, authorization, and guard consumers. Every derived report retains the
resolved policy and source digest.

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
- `model_comparison.py` validates and compares complete model behavior artifacts offline.
- `calibration.py` calibrates saved semantic scores and validates them against human labels.
- `contract_diff.py` compares scan graphs and maps changes to affected behavior scenarios.
- `baseline.py` validates and deliberately promotes contract baseline candidates.
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
