# API Authentication

Source: https://accessgrid.com/docs

Snapshot taken 2026-05-20. Re-fetch if AccessGrid changes the auth model — this is wire-level critical, getting it wrong silently breaks every signed request.

## TL;DR

Every request carries two headers:

| Header | Value |
|--------|-------|
| `X-ACCT-ID` | Your account ID (static, from AG console → API Keys) |
| `X-PAYLOAD-SIG` | Hex-encoded HMAC-SHA256 of the base64-encoded payload, signed with your secret key |

The official SDKs handle this. **Only read this file in detail if you're porting to a language without an SDK** (see [no-sdk-porting.md](./no-sdk-porting.md)).

## Credentials

- **Account ID** and **Shared Secret** live in the AccessGrid console on the API Keys page.
- Export as environment variables:
  ```bash
  export ACCOUNT_ID="<your account id>"
  export SECRET_KEY="<your shared secret>"
  ```
- The .NET SDK reads `ACCESSGRID_ACCOUNT_ID` / `ACCESSGRID_SECRET_KEY` (prefixed). Other SDKs use the bare names. Match what your SDK expects or alias env vars in deployment config.

## The signature algorithm

**`HMAC_SHA256(key=secret_key, data=base64(payload)).hexdigest()`**

The exact `payload` depends on the HTTP method:

| Method | What goes into `payload` |
|--------|---------------------------|
| `POST` / `PATCH` / `PUT` | The JSON request body, as a string |
| `GET` / `DELETE` | The value of the `sig_payload` query parameter — `{}` if no body / no scoped payload |

In all cases the `payload` string is **base64-encoded** before being fed into HMAC, and the HMAC output is **hex-encoded** before being placed in the `X-PAYLOAD-SIG` header.

### Worked example — POST

```python
import base64, hmac, hashlib, json, requests

body = json.dumps({"card_template_id": "0xd3adb00b5", "employee_id": "123"}, separators=(',', ':'))
payload_b64 = base64.b64encode(body.encode()).decode()
sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()

requests.post(
    "https://api.accessgrid.com/v1/key-cards",
    data=body,                                          # send the EXACT bytes you signed
    headers={
        "Content-Type": "application/json",
        "X-ACCT-ID": ACCOUNT_ID,
        "X-PAYLOAD-SIG": sig,
    },
)
```

**Gotcha:** JSON serializers may reorder keys, add whitespace, or change escaping between sign-time and send-time. Sign the *exact byte string* you transmit. If you serialize twice with different settings, signatures will fail intermittently.

### Worked example — GET / DELETE

```python
sig_payload = "{}"                                     # or scoped JSON if the endpoint takes one
payload_b64 = base64.b64encode(sig_payload.encode()).decode()
sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()

requests.get(
    "https://api.accessgrid.com/v1/key-cards/0xc4rd1d",
    params={"sig_payload": sig_payload},               # include the literal payload as query param
    headers={"X-ACCT-ID": ACCOUNT_ID, "X-PAYLOAD-SIG": sig},
)
```

The `sig_payload` query parameter is **part of the request the AG server reconstructs to verify** — don't omit it.

## Rate limits

Documented limits (Android pass provisioning / Google Wallet calls):

- **5 concurrent connections** per account
- **20 requests per second** per account

These are the only published numbers. Apple Wallet provisioning and console operations may have separate undocumented limits — implement defensive client-side throttling regardless.

For bulk operations (backfills, mass re-provisioning), use a token-bucket limiter on the client side. Contact AG support before sustained high-volume runs.

## Retry behavior

- Retry `429` honoring `Retry-After` if present, else exponential backoff with jitter.
- Retry `5xx` up to 3 times with exponential backoff.
- **Do not retry** `400`, `401`, `403`, `404`, `409`, `422` — these signal a request-shape problem, not transient failure.

## Base URL

The production base URL is `https://api.accessgrid.com`. Sandbox / staging endpoints are not documented publicly — if your account has a separate sandbox, the URL comes from AG support. Always make the base URL configurable; never hardcode.

## Transport requirements

- HTTPS only. TLS verification on.
- Use sane timeouts: 5s connect, 30s read.
- Identify your client with a `User-Agent` header — e.g. `accessgrid-elixir/0.1.0` for a port, or `host-app/1.4.2 (accessgrid-py/x.y.z)` if you want AG to see traffic attribution.

## Things the docs do not specify (verify with AG support if they matter)

- Sandbox base URL.
- Error response shape (assume JSON with `error` / `message` fields; defensively handle non-JSON 5xx bodies).
- Native idempotency keys — none documented. Implement dedupe on the client side using the patterns in [SKILL.md](../SKILL.md) non-negotiables.
- Webhook signature header (separate from API auth — see [webhook-events.md](./webhook-events.md); bearer-token is documented, HMAC is not).

## Common porting failures

1. **Double-encoding the body.** Base64 the *string*, not a JSON-of-a-string.
2. **Re-serializing between sign and send.** Sign the bytes you transmit.
3. **Forgetting `sig_payload` on GETs.** The query parameter is mandatory even when empty (`{}`).
4. **Hex-vs-base64 confusion.** Input to HMAC is base64; output is hex.
5. **Mixing case on header names.** HTTP headers are case-insensitive on the wire, but middlewares (lowercasing proxies, picky frameworks) sometimes care. Send exactly `X-ACCT-ID` and `X-PAYLOAD-SIG` to be safe.
