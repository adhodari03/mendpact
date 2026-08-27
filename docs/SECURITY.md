# Security boundary

OpenProof inspects systems that may be untrusted. Safety therefore depends on keeping discovery,
execution, credentials, and stored evidence within explicit boundaries.

## Implemented in v0.1

- HTTPS is required by default.
- URLs containing embedded credentials are rejected.
- Hostnames are resolved before connection.
- Private, loopback, link-local, multicast, reserved, and unspecified addresses are blocked.
- Local development requires both `--allow-private` and `--allow-insecure-http` when applicable.
- Reports identify heuristic findings as findings rather than certifications.
- The conformance wrapper executes a pinned package with an argument list rather than a shell.
- Only the initialization scenario runs without explicit tool-call authorization.

## Conformance execution

The official conformance suite can invoke MCP tools. A full suite must never be aimed at a
production server unless every possible side effect is understood and accepted. OpenProof
defaults to `server-initialize`; any other scenario or suite requires `--allow-tool-calls` and
should run against an isolated fixture with disposable data and credentials.

The first conformance invocation downloads the pinned npm package through `npx` into an ephemeral
cache rather than modifying the user's global npm cache. Pinning limits unexpected upstream
changes but does not eliminate package-registry or transitive-dependency risk. Hosted execution
will require a prebuilt, verified runner image without runtime installs.

## Known limitation

Pre-connection DNS resolution alone does not fully prevent DNS rebinding because the MCP SDK
performs its own network connection. Before operating OpenProof as a public scanning service,
route all target traffic through an egress proxy that revalidates the connected address and
blocks private ranges.

## Required before stdio/repository scanning

- one ephemeral container or microVM per target;
- read-only root filesystem and fresh workspace;
- no inherited secrets;
- network disabled unless a test explicitly grants an allowlisted destination;
- CPU, memory, process, file-size, and wall-clock limits;
- structured redaction before trace persistence;
- short-lived, least-privilege credentials only.

Security reports should go through a private disclosure process once a public repository exists.
