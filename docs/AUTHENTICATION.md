# Authenticated targets

MendPact can scan an HTTPS MCP endpoint with a pre-issued OAuth bearer token. The token is loaded
only from an environment variable and is attached to every MCP HTTP request through the
`Authorization: Bearer` header. MendPact never accepts a token value as a CLI option, policy
value, target query parameter, or GitHub Action input.

## Credential-free preflight

Run the public metadata audit before creating a secret or granting MendPact access to the MCP
server:

```bash
mendpact auth-check https://api.example.com/mcp \
  --output mendpact-authorization-report.json
```

`auth-check` sends an unauthenticated request only to obtain the Bearer challenge, then reads the
advertised protected-resource and authorization-server metadata. It never reads a token from the
environment, even when the supplied policy names one. The command emits a versioned
`mendpact.authorization.v1` report and uses the same `0`, `1`, and `2` CI exit-code contract as a
scan.

Use `--fail-on medium` to make advisory metadata findings such as missing PKCE `S256`
advertisement block CI. A reviewed `--policy` owns this threshold through `scan_fail_on`; the
command rejects threshold and network-allowance overrides when policy is present.

This is a deployment-readiness check, not authentication. It cannot prove that a future token has
the intended audience or scopes, that an authorization flow will succeed, or that the protected
MCP methods enforce access correctly.

## CLI configuration

Reference the environment variable in the reviewed production policy:

```toml
schema_version = "mendpact.policy.v1"
name = "production"
profile = "production"
bearer_token_env = "MENDPACT_ACCESS_TOKEN"
```

Set the value only in the process environment and run the normal command:

```bash
export MENDPACT_ACCESS_TOKEN='your-short-lived-token'

mendpact scan https://api.example.com/mcp \
  --policy mendpact.toml \
  --output mendpact-scan-report.json
```

Without a policy, `--auth-token-env MENDPACT_ACCESS_TOKEN` provides the same environment-variable
reference. Passing the token itself is rejected because token strings are not valid environment
variable names.

## GitHub Actions

Store the token as a GitHub Actions secret, expose it as an environment variable on the MendPact
step, and keep only the variable name in policy:

```yaml
- id: mendpact
  uses: adhodari03/mendpact@v0.3.0
  env:
    MENDPACT_ACCESS_TOKEN: ${{ secrets.MENDPACT_ACCESS_TOKEN }}
  with:
    target: https://api.example.com/mcp
    policy: mendpact.toml
    output: mendpact-scan-report.json
```

For a run without policy, set `auth-token-env: MENDPACT_ACCESS_TOKEN`. Never put a secret
expression directly in `auth-token-env`; that input is deliberately treated as a variable name.

To audit discovery without exposing a secret to the job, use `mode: auth` and omit both the token
environment variable and `auth-token-env`:

```yaml
- id: mendpact-auth
  uses: adhodari03/mendpact@v0.3.0
  with:
    mode: auth
    target: https://api.example.com/mcp
    policy: mendpact.toml
    output: mendpact-authorization-report.json
```

The Action rejects `auth-token-env` in this mode so an accidental credential configuration cannot
silently widen the audit.

## OAuth metadata inspection

When bearer authentication is configured, MendPact performs a read-only metadata inspection
before connecting with the token. It:

- checks an unauthenticated `WWW-Authenticate` Bearer challenge for `resource_metadata` and
  requested scopes;
- falls back to the path-specific and root RFC 9728 protected-resource well-known URLs;
- requires the protected `resource` identifier to match the MCP target;
- requires at least one HTTPS authorization-server issuer;
- tries the OAuth and OpenID Connect metadata URLs required for issuers with and without paths;
- requires exact issuer matching and HTTPS authorization and token endpoints;
- reports missing PKCE `S256` advertisement;
- refuses private, special-use, credential-bearing, fragmented, or plaintext metadata URLs under
  production policy.

Metadata requests never include the bearer token and do not follow redirects. The resulting URLs,
scopes, status, and findings are retained in the JSON report and GitHub summary. This inspection
does not open a browser, register a client, obtain a token, refresh a token, or execute an MCP tool.

### Authorization finding reference

| Rule | Severity | Meaning |
| --- | --- | --- |
| `MP-AUTH-001` | high | RFC 9728 protected-resource metadata was not found. |
| `MP-AUTH-002` | high | A protected-resource metadata URL was unsafe. |
| `MP-AUTH-003` | high | The protected-resource identifier did not exactly match the MCP target. |
| `MP-AUTH-004` | high | An authorization-server issuer URL was unsafe. |
| `MP-AUTH-005` | high | No authorization-server document with an exact issuer match was found. |
| `MP-AUTH-006` | high | A required authorization or token endpoint was missing or unsafe. |
| `MP-AUTH-007` | medium | PKCE `S256` support was not advertised. |
| `MP-AUTH-008` | high | Protected-resource metadata did not list an authorization server. |

The distinct rule IDs keep policy waivers narrow. For example, waiving a temporarily missing
authorization-server list cannot also waive an unsafe metadata URL.

The implementation follows the MCP 2026-07-28
[authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
and its
[authorization-server discovery requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/authorization-server-discovery).

## Security boundary

MendPact defensively redacts the configured token from captured MCP exceptions. Reports retain
the environment-variable name for auditability, but never its value. Use a short-lived token issued
for the exact MCP resource and least-privilege scopes; MendPact cannot prove the audience or claims
of an opaque pre-issued token. Rotate or revoke the credential in the issuing system if exposure is
suspected.
