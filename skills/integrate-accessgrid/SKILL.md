---
name: integrate-accessgrid
description: Integrate AccessGrid mobile credentials into an existing PACS or credentialing codebase. Use when you need to add provisioning, lifecycle sync, card template setup, or webhook/sync-agent handling for Apple Wallet or Google Wallet credentials.
---

# Integrate AccessGrid

Use this skill when the job is to add AccessGrid to an existing product, not to build a standalone demo. The goal is a host-app integration that fits the current architecture, maps PACS entities cleanly, and can be operated without manual cleanup.

Read only what you need:

- Read [references/discovery-and-planning.md](./references/discovery-and-planning.md) when you need the repo-inspection checklist, routing matrix, and delivery artifacts.
- Read [references/python.md](./references/python.md) first when the host stack is Python. This is the primary reference.
- Read [references/go.md](./references/go.md) when the host stack is Go.
- Read [references/java.md](./references/java.md) when the host stack is Java.
- Read [references/csharp.md](./references/csharp.md) when the host stack is C# or .NET.
- Read [references/node-typescript.md](./references/node-typescript.md) when the host stack is Node.js or TypeScript.
- Read [references/ruby-on-rails.md](./references/ruby-on-rails.md) when the host stack is Rails.
- Read [references/laravel-php.md](./references/laravel-php.md) when the host stack is Laravel or PHP.
- Run `python3 scripts/scaffold_mapping_doc.py <system-name>` when the host project needs a starter mapping document.

## Operating Rules

- Start by reading the host codebase. Do not invent its models, queues, webhook style, or deployment shape.
- Prefer extending existing services, jobs, controllers, and admin screens over adding a parallel integration subsystem.
- If the product already has patterns for providers like Twilio, Stripe, or other external APIs, copy those patterns for config, retries, logging, and testing.
- Treat duplicate issuance as a production bug. Idempotency and reconciliation are required, not optional hardening.
- Keep volatile API details in official AccessGrid docs or SDK docs. This skill is for workflow, decisions, and quality gates.
- Preserve official AccessGrid terminology in code and docs: `Access Pass` in product language, `access_cards` or `AccessCards` in SDK-facing code, and `console` for console-managed resources.

## First Pass

Before writing code, inspect the host project and answer:

1. Deployment model: `cloud` or `on-prem`
2. Integration depth: `simple`, `comprehensive`, or `deep`
3. Source workflow: event-driven, polling, or mixed
4. Sync direction: `PACS->AG` only or bidirectional
5. Credential source: `site_code/card_number`, raw bytes, or another representation
6. Delivery owner: AccessGrid-managed messaging or host-app delivery of `install_url`
7. Tenant model: single-tenant or multi-tenant

If the user has not answered these, infer as much as possible from the repo, then state the assumptions you are using in the work. Use the discovery checklist in `references/discovery-and-planning.md` rather than inventing a structure from memory.

After discovery, choose the language reference that matches the host stack and stay in that file unless you need a pattern from another stack.

## Execution Path

### Step 1: Map the Domain

Create a concrete mapping before coding. Use the template from `scripts/scaffold_mapping_doc.py` if the host project does not already have an integration-doc format.

- Host cardholder identifier -> AccessGrid cardholder fields
- Host credential identifier -> `metadata.pacs_credential_id`
- Tenant/site identifiers -> AccessGrid grouping fields or config references
- Host lifecycle states -> `provision`, `resume`, `suspend`, `delete`
- Credential payload source -> exact transform used for AccessGrid

Do not leave this as implicit code behavior. Write it down.

### Step 2: Choose the Smallest Viable Track

#### Track A: `simple`

Use when the host app only needs to issue and manage credentials using existing AccessGrid templates.

Implement:

- AccessGrid client/auth setup
- Provision flow
- Suspend, resume, and delete flows
- Idempotency key or deterministic dedupe behavior
- Basic operator-facing error visibility

Reference implementation patterns:

- Python: `references/python.md`
- Go: `references/go.md`
- Java: `references/java.md`
- C#/.NET: `references/csharp.md`
- Node/TypeScript: `references/node-typescript.md`
- Rails: `references/ruby-on-rails.md`
- Laravel/PHP: `references/laravel-php.md`

Do not implement:

- AccessGrid template CRUD
- Landing page CRUD
- Deep credential-profile or SmartTap automation

#### Track B: `comprehensive`

Use when the host app must manage more of the AccessGrid configuration itself.

Implement everything in `simple`, plus:

- Card template creation/update/publish flow
- Landing page strategy and storage of template/page references
- Webhook receiver and reconciliation if the product is cloud-hosted
- Per-tenant config persistence if the host app is multi-tenant

Reference implementation patterns:

- Python: `references/python.md`
- Go: `references/go.md`
- Java: `references/java.md`
- C#/.NET: `references/csharp.md`
- Node/TypeScript: `references/node-typescript.md`
- Rails: `references/ruby-on-rails.md`
- Laravel/PHP: `references/laravel-php.md`

#### Track C: `deep`

Use when the host app is expected to fully manage advanced AccessGrid setup and support workflows.

Implement everything in `comprehensive`, plus:

- Credential profile automation
- Secure key generation and encrypted persistence
- Reveal-once handling where required
- Template-pair management
- Strong auditability and support tooling

Only choose `deep` if the host product actually needs these features now.

### Step 3: Fit the Architecture

#### If `cloud`

Preferred pattern:

- Host event or webhook triggers provisioning/update
- AccessGrid webhook updates host state

Required behavior:

- Signature validation for inbound webhooks
- Replay protection
- Idempotent processing keyed by event ID or deterministic business key
- Retry only for `429` and `5xx`

See the host language reference listed above for the webhook skeleton.

#### If `on-prem`

Preferred pattern:

- Long-running sync worker reconciles PACS state with AccessGrid

Required behavior:

- Durable checkpoints or watermarks
- Safe restart semantics
- Permanent failure queue or equivalent operator-visible error state

See `references/python.md` for the primary polling-agent skeleton. Mirror the same checkpoint and replay rules in Go, Java, and C# when those stacks run long-lived agents.

### Step 4: Implement a Vertical Slice First

Before broadening scope, get one credential all the way through:

1. Select one real issuance path.
2. Implement provisioning with correct metadata and mapping.
3. Persist the AccessGrid card/pass identifier back to the host model.
4. Implement suspend/resume/delete from the same source record.
5. Verify replay of the same source event does not create duplicates.

After that works, generalize to bulk flows, additional tenants, or admin tooling.

## Non-Negotiables

### Idempotency and Dedupe

- Every provisioning path must be safely replayable.
- Store enough state to correlate host credential ID to AccessGrid object ID.
- If the network fails after a create call, the retry path must not blindly create another credential.

Preferred keys:

- Source event ID if trustworthy
- Otherwise a deterministic key from tenant plus host credential ID plus operation

### Retry Policy

Retry:

- HTTP `429` while respecting `Retry-After`
- HTTP `5xx`

Do not retry automatically:

- `400`
- `401`
- `403`
- `404`
- `409`
- `422`

Surface terminal failures in the host app’s normal error path.

### Observability

Every integration action should be traceable with:

- Host credential/cardholder ID
- Tenant/site ID if applicable
- AccessGrid object ID once known
- Operation name
- Outcome
- Correlation ID or request ID if the stack supports it

### UX Constraints

- Use existing host-app UI patterns.
- Do not build a separate admin app for v1.
- Issuance UI must disclose billable events if issuance incurs cost.
- Placeholder art assets must be clearly labeled as non-production.

## Testing and Verification

Minimum acceptable verification:

1. Provision one credential successfully.
2. Install or confirm install flow for the target wallet platform.
3. Suspend the credential.
4. Resume the credential.
5. Delete or revoke the credential.
6. Replay the original issuance trigger and confirm no duplicate is created.

If automated tests are practical in the host codebase, add them around:

- Mapping logic
- Lifecycle decision logic
- Dedupe behavior
- Webhook signature validation or sync checkpoint logic

Use the examples in the language-specific reference to match the host test style.

## Completion Standard

The integration is not done until all of these are true:

- The host app can issue a credential from its normal workflow.
- Lifecycle updates stay in sync without manual database edits.
- Duplicate source events do not create duplicate credentials.
- Required secrets/config are documented and loaded correctly.
- Another engineer can identify where mapping, retries, and reconciliation live.

## What To Avoid

- Building a demo path that bypasses host models
- Hardcoding tenant-specific IDs without documenting where they belong
- Shipping provisioning without storing the returned AccessGrid identifier
- Creating new UI conventions when the product already has established ones
- Copying volatile API schemas into this skill instead of checking official docs
