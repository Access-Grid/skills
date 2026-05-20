---
name: integrate-accessgrid
description: Integrate AccessGrid mobile wallet credentials (Apple / Google / Samsung) into an existing software system. Use when adding issuance, lifecycle management, template management, credential profiles, landing pages, or webhook handling to a host app — at any of four integration levels (MVP, Essential, Complete, Premium).
---

# Integrate AccessGrid

Adds AccessGrid to an existing product as a phased, host-fitting integration — not a standalone demo. The goal is code that lives inside the host's normal patterns (its models, queues, controllers, secrets, admin UI) at one of four well-defined scope tiers.

This skill is for **integration** into a working codebase. If the user wants a standalone proof-of-concept, that is a different job and this skill will likely over-deliver.

## Operating rules

- **Read the host codebase first.** Do not invent its models, queues, secrets story, webhook conventions, or deployment shape. Mirror what already exists for providers like Stripe, Twilio, SendGrid.
- **Match the host's conventions** for migration tooling, ORM, encryption-at-rest, background jobs, and admin UI. Do not introduce a new dependency when one already exists.
- **Preserve AccessGrid terminology** in code and docs: `Access Pass` in product language, `access_cards` / `AccessCards` in SDK-facing code, `console` for console-managed resources, `X-ACCT-ID` and `X-PAYLOAD-SIG` as the auth headers.
- **Treat duplicate issuance as a production bug.** Idempotency and reconciliation are required, not optional hardening.
- **Volatile API specifics live in the official docs and SDK READMEs**, not in this skill. Snapshotted reference articles are noted as snapshots and should be re-fetched if AG ships material changes.
- **Don't shortcut destructive operations.** Do not delete templates or webhooks on the AG side without an explicit operator action; reconciliation should prefer reading state over forcing it.

## The seven phases

Run these in order. Do not jump ahead — each phase locks decisions that the next depends on.

| # | Phase | Output |
|---|-------|--------|
| 1 | Language and SDK | SDK installed (or porting plan if no official SDK) |
| 2 | Design session | Integration level + UI/API choice locked |
| 3 | Database discovery | The four canonical tables identified or created |
| 4 | Migrations | Host schema updated for the chosen level |
| 5 | Secrets and client wiring | AG client reachable from host code |
| 6 | Endpoints and lifecycle | Provision / suspend / resume / unlink / delete wired |
| 7 | Webhooks | Receiver live, dedup, state mapping correct |

Maintain a running mapping document in the host repo (e.g. `docs/accessgrid-mapping.md`) that captures every decision made across the seven phases — language, integration level, UI/API choice, the four canonical table mappings, secrets locations, webhook subscriptions, encryption mechanisms, backfill plan. Write it as you go and refer back instead of re-asking the user. The contents are dictated by what each phase records below; there is no fixed template.

---

## Phase 1 — Language and SDK

**Ask first, before anything else:** "What language is your platform built in?" AND PRESENT OPTIONS!

### If the language has an official SDK

JavaScript / TypeScript, Ruby, Go, Python, C# / .NET, Java, PHP — install the SDK per the matching reference file:

| Language | Reference |
|----------|-----------|
| JavaScript / TypeScript | [references/node-typescript.md](./references/node-typescript.md) |
| Ruby (incl. Rails) | [references/ruby-on-rails.md](./references/ruby-on-rails.md) |
| Go | [references/go.md](./references/go.md) |
| Python | [references/python.md](./references/python.md) |
| C# / .NET | [references/csharp.md](./references/csharp.md) |
| Java | [references/java.md](./references/java.md) |
| PHP (incl. Laravel) | [references/laravel-php.md](./references/laravel-php.md) |

Each reference file contains: install command, minimum runtime version, client init, provisioning / lifecycle method signatures, webhook receiver, and encryption-at-rest guidance.

**Check the SDK repo's Releases page** for the latest version before pinning. The reference files use the latest version as of skill snapshot date; releases ship.

The SDK handles auth signing transparently. If you need to understand the wire format (debugging signature failures, building a raw-HTTP adapter for an unsupported endpoint), see [references/api-authentication.md](./references/api-authentication.md).

### If the language does not have an official SDK

Examples: Elixir, Rust, Kotlin (not via the Java SDK), Scala, Crystal, Clojure, F#.

Read [references/no-sdk-porting.md](./references/no-sdk-porting.md) and [references/api-authentication.md](./references/api-authentication.md). Workflow:

1. Read [references/api-authentication.md](./references/api-authentication.md) — this is the wire-level signing spec, the most failure-prone part of a port.
2. Read https://github.com/Access-Grid/accessgrid-py end-to-end. It is the reference implementation.
3. Read https://accessgrid.com/docs for endpoint shapes and rate limits.
4. Port only the surface the chosen integration level needs (Phase 2).
5. Test parity against the Python SDK before deploying.

---

## Phase 2 — Design session

A short, structured conversation with the user. Don't skip this — the choices made here drive every subsequent migration and endpoint.

### Step 2a — Integration level

Ask: "There are four levels of integration. Which one do you want?"

| Level | What it gives you | Reference |
|-------|---------------------|-----------|
| **MVP** | Static templates pre-created in the AG console; issuance + lifecycle + webhooks | [references/integration-mvp.md](./references/integration-mvp.md) |
| **Essential** | MVP + dynamic templates as DB rows + webhooks as DB rows | [references/integration-essential.md](./references/integration-essential.md) |
| **Complete** | Essential + editable templates with branding + credential profiles + bundles + operator UI | [references/integration-complete.md](./references/integration-complete.md) |
| **Premium** | Complete + landing pages + ledger items | [references/integration-premium.md](./references/integration-premium.md) |

Each level is strictly cumulative — Essential includes everything in MVP, etc.

Recommend **Essential** as the default starting point unless the user has a strong reason to go lower (one-product host with no per-tenant customization → MVP) or higher (customer-facing dashboard for AG management → Complete or Premium).

### Step 2b — UI / API / Both

Ask: "Do you want a UI implementation, an API implementation, or both?"

- **API.** Endpoints in the host's existing API surface; lifecycle as REST or RPC matching house style.
- **UI.** New screens in the host admin / operator dashboard.
- **Both.** UI calls the same API.

The integration-level reference files spell out what UI and API look like at each tier.

### Lock the choices in the mapping doc

After the user answers, write integration level and UI/API choice into the mapping doc (section 2). Don't re-ask later.

---

## Phase 3 — Database discovery

Locate the four canonical concepts AccessGrid binds to. Use [references/database-discovery.md](./references/database-discovery.md) for the discovery procedure and the prompt pattern.

The four concepts:

1. **Credential Holders** — people the credentials belong to (often `users`, `identities`, `people`)
2. **Credentials** — the actual cards / passes (often `credentials`, `cards`, `badges`)
3. **Credential Formats** — bit format definitions (often `card_formats`, `bit_formats`)
4. **Event Logs** — audit / activity trail (often `events`, `audit_logs`, `activities`)

**Confirm with the user one concept at a time.** Don't batch — give them space to think:

> "Which table best represents the idea of **Credential Holders** in your existing system?
> A. `users`  B. `identities`  C. `people`  D. Something else (type it)"

If a concept is missing, walk the user through creating it before any AG migration. All four are required even for MVP.

Also ask: "Should the 'is mobile wallet credential' flag live on the Credential Formats table or the Credentials table?" — both valid; record the answer.

---

## Phase 4 — Migrations

### General migration (every level)

On the **Credentials** table:

- `accessgrid_id` — string(64), nullable, indexed, unique-when-not-null
- `state` — enum (`created`, `active`, `suspended`, `unlink`, `deleted`); see [references/pass-state-transitions.md](./references/pass-state-transitions.md)

On Credentials **or** Credential Formats (per the user's choice in Phase 3):

- `is_mobile_wallet_credential` — boolean, not null, default false

Per-framework migration snippets are in [references/integration-mvp.md](./references/integration-mvp.md).

### Level-specific migrations

Apply on top of the general migration:

- **MVP:** nothing further. Three template IDs live in env vars.
- **Essential:** see [references/integration-essential.md](./references/integration-essential.md) — `card_templates`, `card_template_credential_formats`, `webhooks`.
- **Complete:** see [references/integration-complete.md](./references/integration-complete.md) — adds branding columns to `card_templates`; adds `credential_profiles`, `credential_profile_keys`, `credential_profile_files`, `card_template_bundles`.
- **Premium:** see [references/integration-premium.md](./references/integration-premium.md) — adds `landing_pages`, `ledger_items`.

### Validations to add at the ORM layer

- **Enums** must use the host's enum mechanism (`enum` in Rails, `choices=` in Django, ENUM in MySQL/Postgres, TS union types, etc.).
- **Image dimensions and formats** on `card_templates.logo` / `background` / `icon` — see [references/image-dimensions.md](./references/image-dimensions.md). Reject before upload, surface clear errors.
- **Color fields** validate as hex (`#RRGGBB` or `#RRGGBBAA`).
- **Bearer tokens and key values MUST be encrypted at rest.** Per-framework mechanisms are in [references/integration-essential.md](./references/integration-essential.md).
- **`card_template_bundles`**: at-least-one-platform CHECK constraint.
- **`landing_pages`**: enforce universal/personalized mutual exclusivity (universal → no password; personalized → no `allow_immediate_download`).

---

## Phase 5 — Secrets and client wiring

Store these secrets in whatever mechanism the host already uses (env vars, vault, encrypted credentials file, KMS). **Never in plaintext source control.**

Always required:

- `ACCESSGRID_ACCOUNT_ID`
- `ACCESSGRID_SECRET_KEY`

MVP-only (templates and webhook bearer are env-resident at MVP, then move to DB at Essential+):

- `ACCESSGRID_IOS_TEMPLATE_ID`
- `ACCESSGRID_ANDROID_TEMPLATE_ID`
- `ACCESSGRID_SAMSUNG_TEMPLATE_ID`
- `ACCESSGRID_WEBHOOK_BEARER`

Ask the user: "Do you operate a separate sandbox / dev AG account from prod?" — if yes, double every secret with the host's environment-split convention.

Wire the SDK client in the host's standard place for external clients — service provider (Laravel), initializer (Rails), DI container (Spring/.NET), package-level singleton (Go), etc. See the per-language reference file.

---

## Phase 6 — Endpoints and lifecycle

Build a **vertical slice first.** Before broadening scope, get one credential all the way through:

1. Issue one credential via the host's normal flow.
2. Persist `accessgrid_id` and `state=created` on the host record.
3. Confirm install on a real device (iOS *and* Android).
4. Suspend, resume, unlink, delete — each via host UI/API.
5. Replay the original issuance trigger. **No duplicate.**

Only after that works, generalize to bulk flows, multi-tenant, admin tooling, etc.

### Endpoint design

The integration-level reference files describe the endpoints per level. Defaults:

- **Provision**: `POST /credentials/:id/wallet-pass` → `{ install_url, accessgrid_id, state }`
- **Suspend / Resume / Unlink**: `POST /credentials/:id/wallet-pass/(suspend|resume|unlink)`
- **Delete**: `DELETE /credentials/:id/wallet-pass`
- **Template CRUD** (Essential+): `/card-templates` REST resource
- **Webhook registration CRUD** (Essential+): `/accessgrid-webhooks` REST resource
- **Credential profile CRUD** (Complete+): `/credential-profiles`
- **Landing page CRUD** (Premium): `/landing-pages`
- **Ledger read** (Premium): `/ledger` (read-only)

Match the verb style and URL convention the host already uses (action endpoints vs sub-resource PATCH). Don't introduce a third pattern.

### Use the SDK

Heavily prefer SDK methods over raw HTTP. The SDK handles signing, error parsing, and resource serialization. Per-language method names are in the reference files.

### Idempotency

Before calling `client.access_cards.provision(...)`, check if the host credential already has an `accessgrid_id`. If yes, fetch the existing pass and return its install URL instead. Storage of the AG ID **must succeed before** the operation is considered complete — wrap in a transaction or compensate on persistence failure.

---

## Phase 7 — Webhooks

Read [references/webhook-events.md](./references/webhook-events.md) for the full event catalog, recommended subscriptions per integration level, transport (CloudEvents 1.0), and receiver non-negotiables.

### Subscribe to (per level)

- **MVP**: All `ag.access_pass.*` + `ag.webhook.cert_expiring` + `ag.account_balance.low`
- **Essential**: MVP + all `ag.card_template.*`
- **Complete**: Essential + all `ag.credential_profile.*`
- **Premium**: Complete + all `ag.landing_page.*` + `ag.account.impersonation_*`

### Map events to credential state

The `state` enum on Credentials mirrors AccessGrid pass states. See [references/pass-state-transitions.md](./references/pass-state-transitions.md) for the full state machine and event→state table.

### Receiver non-negotiables

1. Verify bearer token (or mTLS) on every request. 401 on mismatch.
2. Validate envelope: `specversion == "1.0"` and `source == "accessgrid"`. 400 on mismatch.
3. Dedupe by `id`. TTL ≥ 7 days.
4. Handle unknown `type` by logging and returning 200 — do not 500 on a new event.
5. Always return `{"received": true}` with 200/201 on success. Anything else triggers up to 6 hours of AG retries.
6. Process async if work might exceed ~5 seconds.
7. Idempotent state writes. Re-applying suspend on an already-suspended credential is a no-op, not an error.

---

## Non-negotiables (apply at every level)

### Idempotency and dedupe

- Every provisioning path must be safely replayable.
- Store enough state to correlate host credential ID ↔ AccessGrid object ID.
- If the network fails after `provision`, the retry path must not blindly create another credential.

Preferred dedupe keys: source event ID if trustworthy, else a deterministic key from tenant + host credential ID + operation.

### Retry policy

Retry:
- HTTP `429` while respecting `Retry-After`
- HTTP `5xx` with exponential backoff and jitter, max 3 attempts

Do not retry automatically:
- `400`, `401`, `403`, `404`, `409`, `422`

Surface terminal failures in the host app's normal error path.

### Observability

Every integration action should be traceable with:

- Host credential / cardholder ID
- Tenant / site ID if applicable
- AccessGrid object ID once known
- Operation name
- Outcome
- Correlation ID or request ID if the stack supports it

Subscribe `ag.account_balance.low` and `ag.webhook.cert_expiring` to your existing alerting (Slack / pager / email).

### Secrets

- Never commit `ACCESSGRID_SECRET_KEY` or webhook bearer tokens in plaintext.
- Use the host's existing KMS / vault / encrypted credentials store.
- `webhooks.bearer_token` (Essential+) and `credential_profile_keys.key_value` (Complete+) MUST be encrypted at rest in the database.

### UX

- Use existing host-app UI patterns. No separate admin app for v1.
- Issuance UI must disclose billable events if issuance incurs cost.
- Placeholder branding assets must be clearly labeled non-production.

---

## Completion standard

The integration is not done until **all** of these are true:

- [ ] The host app can issue a credential from its normal workflow.
- [ ] Install confirmed on a real device for every target platform.
- [ ] Lifecycle updates stay in sync without manual database edits.
- [ ] Duplicate source events do not create duplicate credentials.
- [ ] Required secrets are documented and loaded correctly.
- [ ] Webhook receiver dedupes and acks per the non-negotiables.
- [ ] Sensitive columns are verified encrypted at rest by inspecting raw DB values.
- [ ] Another engineer can identify where mapping, retries, and reconciliation live.
- [ ] Per-level checklist (in the matching integration-level reference) is fully checked.

---

## What to avoid

- Building a demo path that bypasses host models.
- Hardcoding tenant-specific IDs without documenting where they belong.
- Shipping provisioning without storing the returned `accessgrid_id`.
- Creating new UI conventions when the product already has established ones.
- Copying volatile AG API schemas into this skill instead of consulting official docs.
- Falling back to a default template when the right one can't be found — fail loud, fail clear.
- Bypassing webhook signature / bearer verification "just for dev."
- Storing bearer tokens or credential profile keys unencrypted.
- Letting `is_mobile_wallet_credential` placement be implicit — always ask.
