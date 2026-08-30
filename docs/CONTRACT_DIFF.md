# MCP contract-diff rules

MendPact compares two complete `mendpact.scan.v1` artifacts locally. It does not reconnect to
either MCP endpoint, execute a tool, or call a model provider. The output is a versioned
`mendpact.contract-diff.v1` report designed for CI review.

## Impact levels

- `compatible`: existing clients should continue to work;
- `risky`: the change may alter model routing or accepts behavior that deserves review;
- `breaking`: existing tool calls or capability relationships may stop working.

The default failure threshold is `breaking`. Passing `--fail-on risky` makes both risky and
breaking changes return exit code `1`.

## Capability and graph rules

| Rule | Default impact | Change |
| --- | --- | --- |
| `MP-DIFF-001` | breaking | capability removed |
| `MP-DIFF-002` | risky for tools, compatible otherwise | capability added |
| `MP-DIFF-003` | risky for tools/prompts, compatible otherwise | title or description changed |
| `MP-DIFF-004` | breaking | kind or name changed under the same stable node ID |
| `MP-DIFF-005` | risky | server instructions changed |
| `MP-DIFF-006` | breaking | protocol identifier or negotiated version changed |
| `MP-DIFF-007` | risky for tools, compatible otherwise | capability metadata changed |
| `MP-DIFF-008` | risky | server identity changed |
| `MP-DIFF-009` | compatible | server version changed |
| `MP-DIFF-010` | breaking | capability relationship removed |
| `MP-DIFF-011` | compatible | capability relationship added |

## Input-schema rules

| Rule | Default impact | Change |
| --- | --- | --- |
| `MP-DIFF-100` | breaking when introduced, risky when removed | input schema added or removed |
| `MP-DIFF-101` | breaking | input type changed |
| `MP-DIFF-102` | breaking | argument became required |
| `MP-DIFF-103` | breaking | argument removed |
| `MP-DIFF-104` | compatible | optional argument added |
| `MP-DIFF-105` | breaking | unknown arguments no longer accepted |
| `MP-DIFF-106` | risky | schema now accepts unknown arguments |
| `MP-DIFF-107` | compatible | argument is no longer required |
| `MP-DIFF-108` | breaking | enum introduced or allowed values removed |
| `MP-DIFF-109` | compatible when expanded, risky when removed | enum relaxed |
| `MP-DIFF-110` | breaking | numeric, length, item, or property bound tightened |
| `MP-DIFF-111` | compatible | numeric, length, item, or property bound relaxed |
| `MP-DIFF-112` | breaking | pattern, format, constant, or multiple constraint changed |
| `MP-DIFF-113` | risky | malformed or incomparable bound changed |
| `MP-DIFF-114` | breaking, compatible, or risky | nested property changed between object and boolean schema forms |
| `MP-DIFF-115` | breaking or risky | schema for unknown arguments changed |
| `MP-DIFF-198` | risky | schema composition or conditional logic changed |
| `MP-DIFF-199` | risky | otherwise unclassified schema change |

These classifications are conservative compatibility signals, not proof that a server is safe
or semantically correct. Every change includes before-and-after evidence and a JSON Pointer path
so a maintainer can review the decision.

## Behavioral blast radius

When a behavior suite is supplied, a changed or removed tool is linked to scenarios that expect
or forbid it. A newly added tool is linked to every scenario because it can compete with existing
tools during model selection. This mapping identifies which deterministic replays or live model
checks should be rerun; contract diff itself remains provider-free.

Server node IDs commonly include environment-specific endpoint URLs. MendPact normalizes the
server side of graph relationships during comparison so staging and production scans do not
create false edge changes solely because their hostnames or ports differ.
