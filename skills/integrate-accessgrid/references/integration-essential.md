# Essential Integration

**Scope.** Everything in [MVP](./integration-mvp.md), plus **dynamic card templates managed as database records** and **webhooks managed as database records**. Best balance for teams that want to move fast now and have room to grow.

**When this is the right level.** The host needs more than three templates (e.g., one per tenant, region, or role), or wants the act of "create a new template" to be a host-app operation rather than a console click.

## What carries over from MVP

- Secrets (`ACCESSGRID_ACCOUNT_ID`, `ACCESSGRID_SECRET_KEY`) still required.
- Template-ID env vars are **no longer needed** — template IDs are now rows in the new `card_templates` table.
- Webhook bearer env var is **no longer needed** — bearers live in the new `webhooks` table (encrypted).
- All MVP-level columns (`accessgrid_id`, `state`, `is_mobile_wallet_credential`) are still required on Credentials.

## New tables

### `card_templates`

| Column | Type | Constraint |
|--------|------|------------|
| `id` | PK | host convention |
| `name` | string | not null, user-defined |
| `platform` | enum | `ios`, `android`, `samsung` |
| `protocol` | enum | `desfire`, `hid` |
| `accessgrid_id` | string | not null, indexed, the AG template ID |
| timestamps | datetime | not null |

### `card_template_credential_formats` (join)

A pure join — many templates can be associated with one format, and one format can fan out to multiple templates (typically one per platform).

| Column | Type | Constraint |
|--------|------|------------|
| `id` | PK | host convention |
| `card_template_id` | FK | not null, → `card_templates.id` |
| `credential_format_id` | FK | not null, → `<formats table>.id` |
| timestamps | datetime | not null |
| (unique index) | `(card_template_id, credential_format_id)` | prevent dupes |

### `webhooks`

| Column | Type | Constraint |
|--------|------|------------|
| `id` | PK | |
| `name` | string | not null |
| `accessgrid_id` | string | not null, indexed — the AG webhook ID |
| `auth_method` | enum | `bearer`, `mtls` |
| `bearer_token` | **encrypted string** | nullable (required when `auth_method=bearer`) — **MUST** be encrypted at rest |
| `url` | string | not null |
| `client_certificate` | text or blob | nullable (required when `auth_method=mtls`) |
| `client_certificate_expiration_date` | datetime | nullable |
| timestamps | datetime | not null |

## Encryption-at-rest by framework

**`bearer_token` and (Complete level) `credential_profile_keys.key_value` MUST be encrypted at rest.** Pick the framework-native solution — do not roll your own.

| Framework | Mechanism |
|-----------|-----------|
| Rails 7+ | `encrypts :bearer_token` (built-in ActiveRecord encryption) |
| Django | [`django-cryptography`](https://django-cryptography.readthedocs.io/) or `pgcrypto` columns |
| Sequelize / Prisma (Node) | App-layer envelope encryption using KMS-managed DEK; column stays `bytea`/`bytes` |
| Java (Spring) | JPA `AttributeConverter` calling a KMS or HSM; or Jasypt for simpler setups |
| .NET / EF | `ValueConverter` plus `IDataProtector` / Azure Key Vault |
| Go (GORM) | Custom `Scanner`/`Valuer` using AES-GCM with KMS-fetched key |
| Phoenix / Ecto | `Cloak.Ecto.Binary` |
| Laravel | `protected $casts = ['bearer_token' => 'encrypted'];` |

The KMS / key-management story should match what the host already uses for other sensitive fields (Stripe secrets, OAuth tokens, etc.). Don't introduce a new dependency.

### Migration snippet — Rails

```ruby
class CreateAccessgridEssentialTables < ActiveRecord::Migration[7.1]
  def change
    create_table :card_templates do |t|
      t.string  :name, null: false
      t.string  :platform, null: false # ios, android, samsung
      t.string  :protocol, null: false # desfire, hid
      t.string  :accessgrid_id, null: false
      t.timestamps
    end
    add_index :card_templates, :accessgrid_id

    create_table :card_template_credential_formats do |t|
      t.references :card_template, null: false, foreign_key: true
      t.references :credential_format, null: false, foreign_key: true
      t.timestamps
    end
    add_index :card_template_credential_formats,
      [:card_template_id, :credential_format_id],
      unique: true, name: "ix_ctcf_unique"

    create_table :webhooks do |t|
      t.string  :name, null: false
      t.string  :accessgrid_id, null: false
      t.string  :auth_method, null: false # bearer, mtls
      t.text    :bearer_token             # encrypted at app layer
      t.string  :url, null: false
      t.text    :client_certificate
      t.datetime :client_certificate_expiration_date
      t.timestamps
    end
    add_index :webhooks, :accessgrid_id
  end
end
```

### Migration snippet — Django

```python
class Migration(migrations.Migration):
    operations = [
        migrations.CreateModel("CardTemplate", [
            ("id", models.AutoField(primary_key=True)),
            ("name", models.CharField(max_length=255)),
            ("platform", models.CharField(max_length=16, choices=[...])),
            ("protocol", models.CharField(max_length=16, choices=[("desfire","desfire"),("hid","hid")])),
            ("accessgrid_id", models.CharField(max_length=64, db_index=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        # similar for the join table and webhooks (use django-cryptography for bearer_token)
    ]
```

Apply the same patterns in Sequelize/Knex, EF Core, GORM, Doctrine, Ecto.

## Code to build (additions to MVP)

### Template selection at provision time

The MVP "pick template by platform from env vars" logic is replaced by:

1. Look up the credential's format → `credential_formats`.
2. Find associated templates via `card_template_credential_formats`.
3. Filter by `platform` (caller device or operator choice) and `protocol` (host config).
4. Use `card_templates.accessgrid_id` as the `card_template_id` argument to `client.access_cards.provision(...)`.

If no template matches the (format, platform, protocol) tuple, surface a clear operator-facing error — do **not** silently fall back to a default template.

### Template CRUD

Build host-side CRUD that mirrors operations to AccessGrid:

| Host action | SDK | Notes |
|-------------|-----|-------|
| Create | `client.console.templates.create(...)` | Store returned ID in `card_templates.accessgrid_id`; emit row first then call AG, roll back on failure |
| Update | `client.console.templates.update(...)` | Mirror local changes |
| Publish | `client.console.templates.publish(...)` | Only after Apple/Google review process; gated UI |
| Delete | `client.console.templates.delete(...)` | Cascade detach from formats first |

Listen for `ag.card_template.*` webhooks to reconcile when changes happen out-of-band (someone edited via AG console).

### Webhook CRUD

Build host-side CRUD that mirrors webhook registrations to AccessGrid:

1. Operator creates a webhook in the host UI/API.
2. Host calls `POST /v1/console/webhooks` via SDK.
3. AG returns `webhook.id` and `webhook.private_key`. Persist:
   - `webhooks.accessgrid_id = webhook.id`
   - `webhooks.bearer_token = encrypt(webhook.private_key)`
4. The private_key is shown **once** — if the row write fails, you cannot recover it. Use a DB transaction: write the row with a placeholder, call AG, update with the bearer, commit. On any failure, roll back AND call `client.console.webhooks.delete(...)` to avoid orphan AG-side records.

For mTLS, the operator supplies the client cert; persist `client_certificate` and parse `client_certificate_expiration_date` from the cert's `notAfter`. Set up a daily job (or honor `ag.webhook.cert_expiring`) to surface renewal at least 30 days out.

## UI vs API vs both (Essential additions)

- **API.** REST CRUD for `/card-templates`, `/webhooks` matching host conventions. POST to `/card-templates/:id/publish` for the publishing action (non-CRUD).
- **UI.** New admin sections: "Card Templates" (list, create, edit, publish, delete; show linked formats) and "Webhooks" (list, create, edit, delete; show last delivery status, cert expiry warning).
- **Both.** UI calls the same API endpoints.

## Definition of done (Essential)

All MVP checkboxes, **plus**:

- [ ] `card_templates`, `card_template_credential_formats`, `webhooks` tables created.
- [ ] `webhooks.bearer_token` encrypted at rest, verified by inspecting raw DB column.
- [ ] Operator can create a card template via host UI/API and the AG-side ID is stored.
- [ ] Provisioning correctly selects a template based on (format, platform, protocol).
- [ ] No-template-match path returns a clear, actionable error.
- [ ] Webhook subscribes to `ag.card_template.*` plus the MVP event set.
- [ ] Out-of-band template change in AG console reconciles into the host within one webhook delivery.
- [ ] mTLS cert expiration is surfaced ≥ 30 days before expiry (via `ag.webhook.cert_expiring` or a local cron).
