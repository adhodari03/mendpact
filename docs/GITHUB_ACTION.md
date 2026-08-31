# GitHub Action

MendPact is packaged as a composite GitHub Action in the repository root. Existing scan users
remain on `mode: scan` by default. Guard users select `mode: guard` and provide a committed scan
baseline, plus an optional scenario/replay pair.

The Action installs the MendPact version contained in the referenced Git revision. The first
alpha reference was `v0.1.0`; PR-native feedback is introduced in `v0.2.0`. GitHub recommends
pinning third-party actions to a full commit SHA when an immutable reference is required. Use
`main` only for deliberate pre-release testing.

Every scan and guard run writes a Markdown result to the GitHub job summary and emits bounded
workflow annotations for findings, contract changes, and report errors. These presentation steps
do not change MendPact's configured pass/fail thresholds. The JSON report remains the complete,
machine-readable source of truth.

The immutable `v0.1.0` tag predates PR-native summaries. Use `v0.2.0` or a later release for this
feedback.

## Scan mode

```yaml
name: MCP reliability

on:
  pull_request:

permissions:
  contents: read

jobs:
  mendpact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - id: mendpact
        uses: adhodari03/mendpact@v0.2.0
        with:
          target: https://your-server.example/mcp
          fail-on: high
          output: mendpact-report.json
      - if: always()
        uses: actions/upload-artifact@v6
        with:
          name: mendpact-report
          path: mendpact-report.json
          if-no-files-found: ignore
```

## Guard mode

The baseline, scenario suite, and replay plan live in the consuming repository and are available
after `actions/checkout`.

```yaml
name: MCP contract guard

on:
  pull_request:

permissions:
  contents: read

jobs:
  mendpact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - id: mendpact
        uses: adhodari03/mendpact@v0.2.0
        with:
          mode: guard
          target: https://your-server.example/mcp
          baseline: mendpact/baseline-scan.json
          scenario: mendpact/scenarios.json
          replay: mendpact/replay.json
          scan-fail-on: high
          contract-fail-on: breaking
          output: mendpact-guard-report.json
          save-scan: mendpact-candidate-scan.json
      - if: always()
        uses: actions/upload-artifact@v6
        with:
          name: mendpact-guard-report
          path: mendpact-guard-report.json
          if-no-files-found: ignore
```

The Action returns the configured paths as `report` and `candidate-scan` outputs. The examples
use the fixed configured path for `if: always()` artifact upload so a failure report can still be
collected. The Action deliberately does not upload artifacts itself, allowing the consuming
workflow to choose retention, permissions, and naming policy.

Private and insecure HTTP targets remain blocked by default. `allow-private` and
`allow-insecure-http` exist only for deliberate test environments, usually on a self-hosted
runner that can reach the endpoint.

GitHub's [action metadata reference](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax)
defines composite inputs and outputs. Its
[composite Action guide](https://docs.github.com/en/actions/tutorials/create-actions/create-a-composite-action)
also recommends consuming an Action through an explicit repository revision.

## Publishing an Action release

1. Merge the release change only after its local `uses: ./` CI smoke test passes.
2. Create a GitHub release from the merged commit with a tag matching the package version, such
   as `v0.2.0`, and title it `MendPact v0.2.0`.
3. Keep the release notes explicit that this is an alpha supporting Streamable HTTP MCP targets.
4. If publishing to GitHub Marketplace, open the root `action.yml`, select the Marketplace
   release banner, accept the Marketplace Developer Agreement if prompted, and publish the same
   release. GitHub will validate the Action name and metadata in that flow.
5. Test the immutable tag from a release-smoke workflow before announcing it.
6. Record the release commit's full SHA so security-conscious users can pin it immutably.

The repository must remain public and keep a single root Action metadata file for Marketplace
publication. Publishing the GitHub Action does not require a PyPI release because the composite
Action installs MendPact directly from its referenced repository revision.
