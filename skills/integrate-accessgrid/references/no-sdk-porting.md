# Porting AccessGrid to a Language Without an Official SDK

Use this when the host stack is **not** one of: JavaScript/TypeScript, Ruby, Go, Python, C#/.NET, Java, PHP. Examples: Elixir, Rust, Kotlin (without using the Java SDK), Scala, Crystal, Clojure, F#.

Two canonical sources to read before writing any port code:

1. [api-authentication.md](./api-authentication.md) — the wire-level signing spec. The most failure-prone part of a port.
2. https://github.com/Access-Grid/accessgrid-py — the reference SDK implementation.

## Step 1 — Read the canonical sources, in this order

1. [api-authentication.md](./api-authentication.md) — header names, HMAC-SHA256 + base64 + hex encoding, GET vs POST payload rules, worked examples, common porting failures. Read this first; signature mistakes silently break everything downstream.
2. `accessgrid-py` source — every module under the package root. Especially:
   - `client.py` (or equivalent) for HTTP transport, auth header construction, retry logic
   - `access_cards.py` for the issuance/lifecycle resource
   - `console/` for templates, webhooks, credential profiles, landing pages, ledger
   - any signature / payload-hashing module — cross-reference against api-authentication.md
3. https://accessgrid.com/docs — endpoint reference, request/response shapes, rate limits
4. https://accessgrid.com/docs/webhook (see snapshot at [webhook-events.md](./webhook-events.md))

## Step 2 — Map the resource surface

The Python SDK exposes these top-level namespaces. Port them to idiomatic equivalents in the target language:

| Python | Description | Required for |
|--------|-------------|---------------|
| `client.access_cards` | provision, update, list, get, suspend, resume, unlink, delete | MVP |
| `client.console.templates` | template CRUD + publish | Essential |
| `client.console.webhooks` | webhook registration CRUD | Essential |
| `client.console.credential_profiles` | profile CRUD, keys, files | Complete |
| `client.console.landing_pages` | landing page CRUD + attach | Premium |
| `client.console.ledger` | ledger read | Premium |
| `client.console.event_logs` | event log read | optional |
| `client.console.hid.orgs` | HID org create/activate/list | only if using HID protocol |

You do **not** need to port the entire surface up front — port only what the chosen integration level requires.

## Step 3 — Port the transport and auth correctly

**Read [api-authentication.md](./api-authentication.md) first.** It is the canonical wire-level spec — HMAC-SHA256 over base64-encoded payload, hex-encoded signature in `X-PAYLOAD-SIG`, with method-specific payload rules (body for POST/PATCH/PUT; `sig_payload` query parameter for GET/DELETE). Common porting failures and worked examples are there.

Beyond auth, the transport non-negotiables are:

- **HTTPS only.** TLS verification on.
- **Timeouts.** Connect timeout 5s, read timeout 30s as a sane default.
- **Retry policy** (matches the rest of this skill):
  - Retry `429` honoring `Retry-After`.
  - Retry `5xx` with exponential backoff + jitter, max 3 retries.
  - Do **not** retry `400`, `401`, `403`, `404`, `409`, `422` — surface to caller.
- **Rate limits.** 5 concurrent + 20 req/sec for Android/Google Wallet provisioning. Implement a token-bucket if the host is making bulk calls.
- **User-Agent** identifying your port (e.g., `accessgrid-elixir/0.1.0`) so AG can see traffic from custom clients.

## Step 4 — Test parity against the Python SDK

For each ported method:

1. Make the same call from the Python SDK using a sandbox account.
2. Capture the request (use a proxy like mitmproxy, or AG's request log).
3. Make the same call from your port and compare:
   - URL path
   - Headers (especially `X-PAYLOAD-SIG` — see [api-authentication.md](./api-authentication.md) for how it's computed)
   - Request body byte-for-byte (the exact bytes you signed must equal the bytes you send)
4. Compare responses for structural parity.

If you skip this step, expect signature failures and silent payload divergences in production.

## Step 5 — Publish, but cautiously

If the port is good enough for the host project, that's the bar. Don't ship it as a library unless you can commit to keeping pace with `accessgrid-py` changes. Internal-only is fine.

## Anti-patterns to avoid

- **Don't reimplement against the docs alone.** Docs lag the SDK. The Python implementation is the truth.
- **Don't skip retry logic.** AG occasionally returns 429 or 502; without retries, your provisioning flow becomes flaky.
- **Don't hardcode endpoints.** Use a `base_url` config (defaults to `https://api.accessgrid.com`) so dev/sandbox/prod can be swapped.
- **Don't log request bodies at INFO.** They contain PII (employee email, name) and sometimes raw credential payloads. DEBUG only, and even then redact.
- **Don't roll your own HMAC.** Use the language's standard crypto library.

## When in doubt, ask AccessGrid

If the wire format is ambiguous or undocumented, file an issue on the Python SDK repo or contact AG support. Better to clarify than to ship a port that silently corrupts signatures for one in a thousand requests.
