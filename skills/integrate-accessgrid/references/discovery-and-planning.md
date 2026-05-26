# Discovery and Planning

Companion to [../SKILL.md](../SKILL.md). Use during Phase 1 (read the host repo), Phase 3 (database discovery), and Phase 6 (billing integration). This file is the *checklist* of what to look for; write findings into the mapping doc the SKILL.md tells you to maintain in the host repo.

## Repo inspection checklist

Find these in the host repo before writing any AG-specific code:

- User / cardholder model
- Credential / badge / card model
- Tenant / site / building / organization model (if multi-tenant)
- Where external-provider clients live (the `Stripe::Client` / `Twilio` / `SendGrid` pattern)
- **Billing provider client and tables** (Stripe / Spreedly / Authorize.net / Chargify / Adyen / Checkout.com etc.) — see [billing.md](./billing.md)
- Where secrets and env vars are defined (and how prod/dev split works)
- Where queues, jobs, workers, or cron processes live
- Where webhook controllers / callback handlers live
- Where admin or issuance UI lives
- Where audit logs / activity logs / event records live
- Where integration docs or ADRs belong
- Where ORM-level validations are written
- Encryption-at-rest convention for sensitive columns

Useful searches:

```bash
rg -n "webhook|callback|signature|HMAC|job|worker|queue|retry"
rg -n "credential|badge|cardholder|site code|facility code|card number"
rg -n "twilio|sendgrid|postmark|stripe|external api|client"
rg -n "tenant|site|organization|building|campus"
rg -n "encrypts|encrypted|cipher|kms|secrets_manager"
rg -n "stripe|spreedly|authorize\\.net|chargify|adyen|checkout\\.com|maxio|recurly|paddle"
rg -n "subscription|invoice|usage_record|line_item|billing"
```

## Required inputs from the user

Collect or confirm before Phase 5 (secrets and client wiring):

- `ACCESSGRID_ACCOUNT_ID`
- `ACCESSGRID_SECRET_KEY`
- Sandbox vs prod AG account split
- Webhook endpoint URL the host will expose
- For MVP: pre-created template IDs (iOS / Android / Samsung)
- For MVP: webhook bearer (shown once at webhook creation in AG console)
- Wallet art assets, or explicit approval to use placeholders during dev

Collect or confirm before Phase 6 (billing integration) — skip if both Step 2c answers were "no charge / bundled":

- Card-template billing model (monthly / annually / none) — Step 2c Question A
- Access-pass billing model (bundled / monthly / annually / per-issuance) — Step 2c Question B
- Billing provider (Stripe / Spreedly / Authorize.net / Chargify / Adyen / Checkout.com / other)
- Billing-table mappings: customer, subscription, subscription item, invoice, invoice line, product/price, usage record (any may be N/A)
- Whether suspended passes continue to be billed (host policy)
- Refund / pro-ration policy on `unlink` and `delete`
- See [billing.md](./billing.md) for the full procedure

## AccessGrid terms to preserve

Use AG's vocabulary in code and docs:

- **Access Pass** — the wallet credential product name in docs
- **`access_cards`** / **`AccessCards`** — the SDK surface for pass lifecycle methods
- **`console`** — the SDK surface for card templates, landing pages, webhooks, credential profiles, ledger
- **`X-ACCT-ID`** / **`X-PAYLOAD-SIG`** — the auth headers for signed API requests

Do not rename these in host-app abstractions unless the codebase already has a strong existing provider pattern.

## Review gate before any AG code lands

Don't start implementation until these are explicit:

- Where the AccessGrid client object will live
- Which host record stores `accessgrid_id`
- Which operation triggers provisioning
- Which operations / signals trigger suspend / resume / unlink / delete
- Which mechanism prevents duplicate issuance (event ID dedupe vs deterministic key)
- Which place exposes terminal failures to operators
- Which integration level the user committed to (Phase 2 output)
- Which UI surface the user committed to (Phase 2 output)
- Which billing model the user committed to (Phase 2 Step 2c output) — and, if non-bundled, which provider and table mappings (Phase 6 output)
