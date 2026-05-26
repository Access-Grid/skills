# Billing Integration

Companion to [../SKILL.md](../SKILL.md). Use during **Phase 2 (Step 2c — Billing model)** to capture the design choices, and during **Phase 6 — Billing integration** to wire them up.

AccessGrid does not collect money from the host's end-customers — the host does. This file is about how AG lifecycle events (template create, pass provision, suspend, resume, unlink, delete) flow into the **host's existing billing infrastructure** so the right charges happen at the right time.

The goal is **billing that lives inside the host's normal patterns** — its existing Stripe/Spreedly/Adyen/etc. client, its existing subscriptions/invoices/customers tables, its existing webhook receivers. Mirror what already exists. Do not introduce a new billing provider, a new schema, or a parallel charging path.

---

## The two billing design choices

These are asked in Phase 2 (Step 2c). Record the answers in the mapping doc — they drive everything in Phase 6.

### Choice 1 — Card templates

> "Do you plan to charge your customers for **card templates** themselves (the design / issuer record), and if so, how?"

| Answer | What it means | Billing primitive |
|--------|---------------|--------------------|
| **Monthly** | Per-template subscription, billed monthly | One subscription line per active `card_templates` row |
| **Annually** | Per-template subscription, billed annually | Same as monthly, annual cycle |
| **No / bundled** | Templates are included in a parent plan or free | No template-specific billing action |

Notes:
- Card-template billing is **only meaningful at Essential+** — at MVP the three templates live in env vars and aren't a per-customer construct.
- "Monthly" and "annually" are the cycle. Per-template **price** is a host-side product/plan decision, not an AG concern.
- If the host already has a "seats" or "products" subscription model, prefer wiring templates as a new product/price inside it rather than a parallel subscription stream.

### Choice 2 — Access passes

> "How do you intend to charge for **Access Passes** (the issued credentials)?"

| Answer | What it means | Billing primitive |
|--------|---------------|--------------------|
| **Bundled into other pricing** | No separate AG-driven charge — the customer's existing plan covers issuance | No-op on provisioning |
| **Monthly per active pass** | Metered usage, billed at end-of-month based on active count | Usage record / metered subscription item |
| **Annually per pass** | Charged upfront at provision; renewal at one-year anniversary | One-off invoice or annual subscription per pass |
| **Per issuance (one-time)** | Each provision creates a one-time charge; no renewal | One-off invoice / charge per provision |

Notes:
- "Per issuance" is treated as an additional valid answer even though the original prompt lists only bundled/monthly/annually. Surface it if the user describes a one-time charge.
- "Monthly per active pass" requires a usage meter — count `credentials` rows where `state IN ('active','suspended')` per billing cycle. **Suspended passes are typically still billed** because the credential still exists in the wallet; confirm with the user.
- Refund behavior on `unlink` / `delete` is host policy. Default: no refund, just stop the meter going forward. Ask the user if their product promises pro-ration.

---

## Discovery — billing provider

After both choices are locked, ask:

> "Which billing platform does your application use today?"
>
> A. Stripe
> B. Spreedly
> C. Authorize.net
> D. Chargify (Maxio Advanced Billing)
> E. Adyen
> F. Checkout.com
> G. Something else (name it)
> H. None yet — billing is manual / not in the codebase

If the answer is H, **stop and surface this to the user.** Building billing infrastructure from scratch is out of scope for an AG integration. Help the user choose a provider, get it integrated as a normal first step, then come back to AG.

If the answer is G, ask which SDK / API surface they use, and treat it like a custom provider — the canonical event→billing-action table below still applies, only the provider-specific code differs.

---

## Discovery — billing tables

Locate (one concept per question, do not batch — same pattern as the four canonical AG tables):

| Concept | What you're looking for | Typical names |
|---------|--------------------------|---------------|
| **Billing customer** | The host record that maps to the provider's customer object | `customers`, `billing_accounts`, `accounts`, `organizations` (often the same as the tenant) |
| **Subscription** | The recurring billing record | `subscriptions`, `plans`, `memberships` |
| **Subscription item / line** | The per-product or per-meter line inside a subscription | `subscription_items`, `subscription_lines`, `plan_items` |
| **Invoice** | Issued bills (one-off or recurring) | `invoices`, `bills`, `charges` |
| **Invoice line / charge** | Individual line items | `invoice_items`, `invoice_lines`, `line_items` |
| **Product / Price** | The catalog of what can be charged | `products`, `prices`, `plans`, `tiers` |
| **Usage record** (metered only) | Quantity reported to the meter for a billing cycle | `usage_records`, `metered_events`, `usage_events` |

Confirm each with the user:

> "Which table best represents the idea of **Subscriptions** in your existing system?
> A. `subscriptions`
> B. `memberships`
> C. `plans`
> D. Something else (type it)"

Record the choices in the mapping doc. Phase 6's implementation reads from these — do not invent new tables.

If a concept doesn't exist in the host because they don't use it (e.g. they bill purely via one-off invoices and have no `subscriptions` table), record "N/A" and skip the corresponding code path. Only add a table if the chosen billing model genuinely requires it (e.g. choosing "monthly per active pass" but having no `usage_records` table — propose adding one or using the provider's API directly with no local mirror).

---

## Mapping AG lifecycle to billing actions

This is the canonical table the Phase 6 code implements. Filter rows by the answers from Phase 2 Step 2c — many will be no-ops depending on the model.

| AG event / host action | Card-template billing | Access-pass billing |
|------------------------|------------------------|-----------------------|
| `card_template` created (host UI) | **Monthly/Annual:** create subscription item for the template's owner. **No/bundled:** no-op. | — |
| `card_template` deleted | **Monthly/Annual:** cancel or remove subscription item; honor host pro-ration policy. **No/bundled:** no-op. | — |
| `access_card.provision` (host issues a pass) | — | **Bundled:** no-op. **Monthly metered:** increment usage record by 1 if pass starts in active state. **Annual:** create one-off invoice or annual subscription. **Per-issuance:** create one-off charge. |
| `ag.access_pass.installed` webhook | — | **Monthly metered:** if billing on install rather than provision, increment here instead. Pick one trigger and document it. |
| `ag.access_pass.suspended` | — | **Monthly metered:** typically still bill (no decrement); confirm host policy. **Annual / per-issuance:** no refund by default. |
| `ag.access_pass.resumed` | — | **Monthly metered:** if suspended passes are *not* billed, re-add to meter here. |
| `ag.access_pass.unlinked` | — | **Monthly metered:** decrement usage at end-of-cycle (or immediately, per host policy). |
| `ag.access_pass.deleted` | — | **Monthly metered:** stop billing going forward. **Annual / per-issuance:** no refund by default. |
| `ag.account_balance.low` (AG-side balance, not customer billing) | Alert ops — this is an AccessGrid commercial signal, not an end-customer billing event. Wire to existing pager/Slack as documented in [webhook-events.md](./webhook-events.md). |

**Triggers are AG webhooks, not local state writes.** The host's billing actions should fire from the AG webhook receiver (Phase 8), not from optimistic local updates. Reason: if AG rejects the provision and the host already billed, the customer is charged for a credential that never existed.

Exception: at MVP, the host may bill at the moment of a successful `client.access_cards.provision(...)` 200 OK response since there's no `ag.access_pass.created` round-trip to wait on. Document the chosen trigger in the mapping doc.

---

## Per-provider integration patterns

Heavily prefer the host's existing SDK and patterns. The snippets below are starting points, not prescriptions.

### Stripe

Setup the host should already have: `Stripe::Client` (or `stripe.Client`), a `stripe_customer_id` column on the customer-equivalent table, and a `stripe_subscription_id` column on subscriptions.

| Billing model | Stripe primitive |
|---------------|--------------------|
| Templates monthly/annual | `SubscriptionItem` on the customer's main `Subscription`, with a `Price` whose recurring interval is `month` or `year`. Quantity = number of active templates. |
| Passes monthly metered | `SubscriptionItem` with a metered `Price`. Report quantity via `subscription_items/<id>/usage_records` per billing cycle. |
| Passes annual | Either a separate `Subscription` per pass (rare), or one-off `InvoiceItem` at provision + a scheduled annual renewal. Prefer one-offs unless the host already runs per-resource subscriptions. |
| Passes per-issuance | `InvoiceItem` + `Invoice.finalize` (or `PaymentIntent` for immediate capture), per provision. |

Idempotency: pass `idempotency_key = "ag_provision_#{credential_id}"` (or analogous) on every Stripe API call so retries don't double-charge.

### Spreedly

Spreedly is a payment vault / gateway abstraction, not a subscription billing platform. If the host uses Spreedly, they likely have a separate subscription mechanism on top (their own DB-driven scheduler, Recurly, etc.). Ask:

> "Spreedly handles the card vaulting and gateway. What schedules and creates the actual charges — your own scheduler, a separate subscription platform, or something else?"

Wire AG events to whatever sits above Spreedly. The Spreedly API itself appears only at charge time: `POST /v1/gateways/:gateway/purchase.json` using a vaulted `payment_method_token`.

For metered models, the host's scheduler reads `credentials` counts at cycle end and issues a `purchase` per customer. For per-issuance, fire a `purchase` synchronously inside the webhook handler — but **only if the customer's billing record is non-delinquent** (host check) to avoid stranding a charged-but-unprovisioned credential.

### Authorize.net

ARB (Automated Recurring Billing) handles subscriptions; CIM (Customer Information Manager) handles vaulted payment profiles. Map:

| Billing model | Authorize.net primitive |
|---------------|--------------------------|
| Templates monthly/annual | `ARBCreateSubscriptionRequest` with `paymentSchedule.interval` = month or year. One subscription per template, or one subscription with a custom amount that recalculates. |
| Passes monthly metered | Authorize.net has no native usage metering. Run a cycle-end host job that totals active passes and uses `ARBUpdateSubscriptionRequest` (or a fresh ARB cycle) with the right amount. |
| Passes annual / per-issuance | `createTransactionRequest` (`authCaptureTransaction`) against the customer's CIM payment profile. |

Always set `refId` to a host-deterministic key — Authorize.net does not have first-class idempotency keys; `refId` is the closest analogue.

### Chargify (Maxio Advanced Billing)

Chargify is purpose-built for subscription billing with components, so most of this maps cleanly:

| Billing model | Chargify primitive |
|---------------|----------------------|
| Templates monthly/annual | `quantity_based_component` on the subscription; set quantity = count of active templates. Use `POST /subscriptions/:id/components/:component_id/allocations`. |
| Passes monthly metered | `metered_component`. Report usage via `POST /subscriptions/:id/components/:component_id/usages` during or at the end of the cycle. |
| Passes annual | `on_off_component` per pass on an annual product, or a one-off via `POST /subscriptions/:id/component_allocations`. |
| Passes per-issuance | `POST /subscriptions/:id/charges` for a one-time charge. |

Set `idempotency_key` on every write; Chargify supports it natively.

### Adyen

Adyen's subscription story runs through **recurring contracts** (stored shopper references + `recurringDetailReference`). There's no first-class "subscription product" — the host stores subscription metadata locally and triggers charges via the Checkout API.

| Billing model | Adyen primitive |
|---------------|-------------------|
| Templates monthly/annual | Host-side scheduler creates `/payments` calls with `shopperInteraction=ContAuth`, `recurringProcessingModel=Subscription`. |
| Passes monthly metered | Same — host meter, host scheduler, one `/payments` call per cycle. |
| Passes annual / per-issuance | One `/payments` call at the trigger event. |

Use `reference` (your idempotent key) on every `/payments` call.

### Checkout.com

Checkout.com's recurring billing uses **payment instruments** (stored cards) and the **Hub** for orchestration. Like Adyen, no native subscription product — host orchestrates.

| Billing model | Checkout.com primitive |
|---------------|------------------------|
| Templates monthly/annual | Host scheduler calls `POST /payments` with `source.type=id` (saved card) and `merchant_initiated=true`. |
| Passes monthly metered / annual / per-issuance | Same — single `POST /payments` per trigger. |

Cko supports `Cko-Idempotency-Key` header — always set it.

### Other / custom

If the user names a different provider (Recurly, Maxio Subscription Management, Paddle, Lago, etc.):

1. Read the provider's docs for their subscription primitives.
2. Apply the same canonical event→billing-action mapping above.
3. Mirror the provider's idempotency mechanism — every provider has one; find it before writing code.

---

## Idempotency and double-bill protection

These rules apply to **every** provider:

- **Every billing API call must be idempotent.** Use the provider's native mechanism (`Idempotency-Key`, `idempotency_key`, `refId`, `Cko-Idempotency-Key`, `reference`, etc.). Build the key from a deterministic input: `{operation}_{credential_id}_{cycle_or_event_id}`.
- **Persist the billing record's external ID before processing the next event.** If you don't store the `invoice_id` / `charge_id` / `usage_record_id`, you cannot recover on retry without risking a duplicate.
- **Wrap the AG state write and the billing write in a host transaction where possible.** Where the billing API is external (always), use a two-phase pattern: insert the host billing row with `status=pending`, call the provider, mark `status=succeeded` only on confirmation. On crash, a reconciler reads `pending` rows and queries the provider for the actual state.
- **Dedupe the AG webhook by event `id` before triggering billing.** The webhook receiver's existing dedupe (Phase 8, TTL ≥ 7 days) protects against double-billing on AG-side retries.
- **Do not bill from optimistic local state.** Bill from AG-confirmed events.
- **Refunds and credits are host policy, not AG policy.** AG never refunds. If the host promises refunds on `unlink` or `delete`, that's a host code path triggered by the webhook receiver — not something AG can do for them.

---

## Reconciliation

At least once a day, run a host job that compares:

1. Active passes / templates per customer in the host DB.
2. Active subscription items / metered usage at the billing provider.

Surface divergences in the host's normal error path (Sentry, Datadog, error ticket queue). Common causes:

- Provider call returned 2xx but the host crashed before persisting the external ID.
- An AG webhook was missed or dropped — receiver should also reconcile from AG (see Phase 8).
- An end-customer was deleted in the host but their subscription was not cancelled at the provider.

The reconciler must be safe to re-run. Use the same idempotency keys as the live path.

---

## UX requirements

- **Issuance UI must disclose billable events** when issuance incurs a charge (already required by SKILL.md). Be explicit: "Issuing this pass will create a charge of $X" or "This pass will be added to your monthly bill."
- **Admin UI must surface billing state per template / per pass** at Essential+. Operators need to see if a template's subscription is delinquent or if a pass failed to meter.
- **Failed charges must not block lifecycle.** A failed bill is an operator alert, not a hard error that prevents `suspend` or `delete`. Lifecycle and billing are coupled but not blocking — log the failure, alert, and let the operator decide.

---

## Definition of done (billing)

- [ ] Both Phase 2 Step 2c answers recorded in the mapping doc.
- [ ] Billing provider and the 7 billing-table mappings recorded in the mapping doc.
- [ ] Card-template billing (if applicable) creates subscription items on `card_templates` create and removes them on delete.
- [ ] Access-pass billing (if applicable) is triggered from AG webhooks, not local state writes — with documented exception for MVP synchronous provisioning.
- [ ] Every billing API call uses the provider's native idempotency mechanism.
- [ ] External billing IDs (`invoice_id`, `subscription_item_id`, `usage_record_id`, etc.) are persisted on the host side before the operation is considered complete.
- [ ] A daily reconciliation job compares host counts against provider state and surfaces divergences.
- [ ] Replaying the same AG webhook does **not** create duplicate charges.
- [ ] Failed billing surfaces in the host's existing alerting; does not block lifecycle.
- [ ] Issuance UI discloses charges to operators / end-users when applicable.
- [ ] No new billing provider was introduced — the host's existing provider was used.
