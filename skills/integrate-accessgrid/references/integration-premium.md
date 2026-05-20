# Premium Integration

**Scope.** Everything in [Complete](./integration-complete.md), plus **host-managed landing pages** (universal and personalized) and **ledger item visibility** in the host operator UI.

**When this is the right level.** The host is selling AccessGrid-powered credentialing as a product to its own customers and wants the entire AG surface area exposed in its dashboard — including the customer-facing install flow (landing pages) and billing visibility (ledger items).

> **Note.** Per the original product spec, Premium builds on **Complete** (not Essential). All Complete capabilities — credential profiles, bundles, branded templates, operator UI — are prerequisites.

## What carries over from Complete

- All MVP, Essential, and Complete migrations and code paths.
- Webhook receiver now also subscribes to `ag.landing_page.*` and `ag.account.impersonation_*`.

## Migration additions

### New: `landing_pages`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `name` | string | not null |
| `kind` | enum | `universal`, `personalized` — required |
| `instruction_text` | string | nullable |
| `background_color` | string | hex, validated |
| `logo` | image | reuse host attachment story |
| `allow_immediate_download` | boolean | nullable; **only valid when `kind = universal`** |
| `password` | string | nullable; **only valid when `kind = personalized`** — consider encrypting at rest |
| `accessgrid_id` | string | not null, indexed (the AG landing page ID) |
| timestamps | datetime | not null |

Add a model-level validation: if `kind = universal`, `password` must be null; if `kind = personalized`, `allow_immediate_download` must be null.

### New: `ledger_items`

Read-mostly mirror of AG-side ledger entries.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `accessgrid_id` | string | not null, **unique**, indexed |
| `amount` | decimal(12,4) | not null — match AG precision |
| `kind` | enum | `debit`, `credit` |
| `created_at` | datetime | not null — the AG event time, not the local insert time |
| `reason` | jsonb | not null — preserve AG payload verbatim |

`updated_at` is optional; ledger items are immutable once written.

### Per-framework migration snippet (Rails example)

```ruby
class CreateAccessgridPremiumTables < ActiveRecord::Migration[7.1]
  def change
    create_table :landing_pages do |t|
      t.string  :name, null: false
      t.string  :kind, null: false # universal, personalized
      t.string  :instruction_text
      t.string  :background_color
      t.boolean :allow_immediate_download
      t.string  :password # consider attribute encryption
      t.string  :accessgrid_id, null: false
      t.timestamps
    end
    add_index :landing_pages, :accessgrid_id

    create_table :ledger_items do |t|
      t.string   :accessgrid_id, null: false
      t.decimal  :amount, precision: 12, scale: 4, null: false
      t.string   :kind, null: false # debit, credit
      t.datetime :created_at, null: false
      t.jsonb    :reason, null: false, default: {}
    end
    add_index :ledger_items, :accessgrid_id, unique: true
  end
end
```

For Postgres-on-Django use `JSONField`; for MySQL/Sequelize use `JSON`. For DBs without JSON support, store as text and parse — but this is an anti-pattern, push back on the user.

## Code to build (additions to Complete)

### Landing page lifecycle

1. Operator creates a landing page (universal or personalized) via host UI/API.
2. Host calls `client.console.landing_pages.create(...)`, persists returned ID into `accessgrid_id`.
3. Operator attaches the landing page to one or more card templates. Host calls the attach SDK method.
4. Host reconciles via `ag.landing_page.created`, `.updated`, `.attached_to_template`.

For personalized pages, the password is per-end-user — surface it to the credential-holder via the host's existing notification channel (email, SMS) at issuance time.

### Ledger items (read-only mirror)

Ledger items in the host DB are written **only** by the webhook receiver — never by operator action. There is no host-side ledger CRUD.

The host UI presents:
- A ledger list view (filter by date range, kind, amount).
- A running balance computed by summing `credit` minus `debit`.
- Drill-down on `reason` JSON for individual line items.

If the host needs a stricter audit trail, add an `event_logs` row for every ledger insert.

### Account impersonation

`ag.account.impersonation_started` / `_ended` should be written to the host's audit log (Event Logs canonical table from [database-discovery.md](./database-discovery.md)) so operators can see when AG support staff acted on the account.

## UI requirements (additions)

- **Landing pages index/detail** — list, filter by kind, create with kind-specific fields shown/hidden, attach to templates, preview where feasible.
- **Ledger view** — list, balance summary, date filters, export to CSV.
- **Audit log surfacing** — impersonation events tagged distinctly.

## Definition of done (Premium)

All Complete checkboxes, **plus**:

- [ ] `landing_pages` and `ledger_items` migrations applied.
- [ ] Universal/personalized validation rules enforced at the model layer.
- [ ] Operator creates a universal landing page, attaches it to a template, and the install flow works end-to-end on a real device.
- [ ] Operator creates a personalized landing page and the credential-holder receives the password through the host's notification channel.
- [ ] Webhook receiver writes `ledger_items` rows from any debit/credit-emitting events; balance is correct against a manual recount.
- [ ] `ag.landing_page.*` events reconcile out-of-band changes.
- [ ] Impersonation events appear in the host audit log.
