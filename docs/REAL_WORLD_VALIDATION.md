# Real-world validation playbook

Purpose: discover interoperability defects, misleading findings, and onboarding friction on
independently developed MCP servers. This is a small qualitative study, not a security audit or
benchmark. The setup is implemented; external target validation has not yet been performed by
this workflow. The local evidence API remains deferred.

## 1. Select and authorize targets

Start with two or three independently maintained implementations, preferably locally runnable
with synthetic data. Record an exact upstream commit/image digest, license, installation steps,
expected capabilities, and permission to test. Read/review upstream startup instructions before
running third-party code; use an isolated environment with no production credentials or mounts.
Public accessibility is not permission to test an endpoint. Do not run a bulk target list.

Cover a small read-only catalog, a richer schema/resource catalog, and (if explicitly approved)
an authenticated HTTPS deployment. MendPact currently scans Streamable HTTP, not stdio-only or
legacy SSE endpoints; record unsupported transports as a coverage gap rather than silently
installing a bridge. Target selection and current upstream instructions are tomorrow's work.

Default scope: two sequential discovery scans per target (each scan makes multiple MCP protocol
requests), then offline analysis. No automatic retries, concurrency, fuzzing, conformance runner,
tool calls, or live model evaluation. Stop on rate limiting, unexpected side effects, auth scope
uncertainty, or server instability. Agree any expansion separately. Metadata discovery is not
proof that a third-party server itself has no side effects.

## 2. Prepare a fresh local workspace

From the repository root, activate the existing development environment:

```bash
source .venv/bin/activate
python scripts/prepare_validation.py 2026-09-07-server-a
```

The script works offline and creates `reports/validation/2026-09-07-server-a/` with a private
directory, strict production and local policies, a review template, and a versioned manifest.
It records the Git revision, dirty-state flag, Python and selected package versions, template
hashes, and a 14-day manual cleanup reminder. It does not read environment-variable values,
contact servers, or assert that tests ran. Existing run directories are never reused. A partial
directory after an I/O failure must be inspected manually; no recursive deletion is attempted.
Use a new label for each target/revision or repeated experiment. `reports/` is already ignored.

The manifest is preparation provenance, not a signed attestation or dependency lockfile.
Prepare again after committing/pulling if you need provenance for that exact clean revision.
Complete the authorization section of `review.md` before running any network command.

## 3. Capture discovery with strict gates

Example for an authorized HTTPS target; replace the placeholder before running:

```bash
umask 077
validation_dir=reports/validation/2026-09-07-server-a
validation_target=https://your-authorized-server.example/mcp
test ! -e "$validation_dir/scan-01.json" && \
  mendpact scan "$validation_target" --policy "$validation_dir/production.toml" \
  --output "$validation_dir/scan-01.json"
validation_exit=$?
printf 'Scan exit code: %s\n' "$validation_exit"
```

Run commands interactively without shell `errexit`; record the exit code immediately. If the
file-existence check fails, the scan did not run: choose a fresh output rather than recording
that check as a scan failure. MendPact's existing scan writer can overwrite paths; the check is
an operator guard, not a concurrent-write guarantee.

For a deliberately isolated loopback HTTP server, use `local-strict.toml` instead. That policy
allows private addresses and HTTP but still fails on high scan findings and risky contract
changes. It is **not** suitable for production and does not restrict addresses to loopback by
itself. Never use the permissive `local-smoke.toml` to make external validation appear green.

Interpret scan exits: `0` gate passed, `1` findings reached the threshold, `2` error/incomplete.
Keep failures as evidence; do not weaken thresholds or add waivers merely to pass the study.
Inspect the full report locally. If authorization remains uncertain, stop and consult the
[authentication guide](AUTHENTICATION.md); a credential-free `auth-check` is an additional
network operation, not part of the default two-scan budget. Credential use needs separate review.

Only if the first scan completes and the agreed budget permits, repeat against the unchanged
server into `scan-02.json`, with the same no-overwrite check and exit-code recording.

## 4. Analyze offline

For two complete captures, compare their catalogs without promoting either as a trusted baseline:

```bash
mendpact diff "$validation_dir/scan-01.json" "$validation_dir/scan-02.json" \
  --fail-on risky --output "$validation_dir/contract-diff.json"
mendpact export-report "$validation_dir/scan-01.json" \
  --output "$validation_dir/evidence.html"
mendpact history add "$validation_dir/scan-01.json" \
  --database "$validation_dir/history.sqlite"
```

The standalone `diff` command uses `--fail-on risky`, not a policy-file option; this matches both
strict scan policies' contract threshold. Record each command's exit separately. Use fresh output
names; export refuses replacement, but not every command does.
Identical counts alone do not establish identical contracts. Failed scans can contain useful
complete evidence; error/partial scans must not be presented as complete coverage.

Review each finding against upstream source/schema documentation. A destructive-looking tool
name is a heuristic concern, not a confirmed exploitable vulnerability. Record suspected false
positives and unknowns separately. Read the generated review template for the evidence fields.
Do not invent replay decisions as proof of actual model behavior; behavioral evaluation is a
separate phase with reviewed scenarios and an explicitly approved provider budget if needed.

## 5. Close out and report honestly

Deliver a reviewed target matrix, reproducible defects, synthetic regression fixtures, and a
sanitized summary of what did/did not work. Mark blocked targets and unsupported features
explicitly. No minimum pass percentage is required: finding useful failures is a valid outcome.
Keep raw reports, server logs, local notes, URLs, and packages in the ignored workspace. Commit
only reviewed documentation and synthetic tests. Do not upload validation directories as CI
artifacts or publish them to GitHub Pages. Sharing requires a separate review and permission.

Delete raw workspaces manually within 14 days or sooner under the target owner's requirements.
The manifest reminder does not enforce deletion; `history prune` only cleans its selected history
database, not raw files or backups. No API server, background scheduler, or paid service is needed.
