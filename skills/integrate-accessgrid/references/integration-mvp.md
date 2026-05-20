# MVP Integration

**Scope.** Issuance, lifecycle management, and webhooks against **static, console-managed card templates**. Three templates are pre-created in the AccessGrid console (one per wallet platform — iOS, Android, Samsung) and their IDs are stored as environment secrets in the host app.

**When this is the right level.** The host has a single product, doesn't need branded per-tenant templates, and isn't ready to manage AG configuration. Get to production fast.

## Secrets required

| Secret | Where | How loaded |
|--------|-------|------------|
| `ACCESSGRID_ACCOUNT_ID` | AG console → Settings | env var / vault |
| `ACCESSGRID_SECRET_KEY` | AG console → API Keys | env var / vault — **never** check in plaintext |
| `ACCESSGRID_IOS_TEMPLATE_ID` | AG console → Card Templates | env var |
| `ACCESSGRID_ANDROID_TEMPLATE_ID` | AG console → Card Templates | env var |
| `ACCESSGRID_SAMSUNG_TEMPLATE_ID` | AG console → Card Templates | env var |
| `ACCESSGRID_WEBHOOK_BEARER` | AG console → Webhooks (private key shown once) | env var |

If the host runs sandbox + prod, all six are doubled (`_DEV` / `_PROD` or use a `RAILS_ENV`-style suffix). Ask the user which split the existing app uses.

## Migration — added columns

Placement of `is_mobile_wallet_credential` depends on the user's answer in [database-discovery.md](./database-discovery.md). The other two columns always live on Credentials.

### On Credentials (always)

| Column | Type | Constraint |
|--------|------|------------|
| `accessgrid_id` | string / varchar(64) | nullable, **indexed**, unique-when-not-null |
| `state` | enum | `created`, `active`, `suspended`, `unlink`, `deleted` — see [pass-state-transitions.md](./pass-state-transitions.md) |

### On Credentials OR Credential Formats (per user choice)

| Column | Type | Constraint |
|--------|------|------------|
| `is_mobile_wallet_credential` | boolean | default `false`, not null |

### Per-framework migration snippets

**Rails (ActiveRecord):**
```ruby
class AddAccessgridToCredentials < ActiveRecord::Migration[7.1]
  def change
    add_column :credentials, :accessgrid_id, :string, limit: 64
    add_index  :credentials, :accessgrid_id, unique: true, where: "accessgrid_id IS NOT NULL"
    add_column :credentials, :state, :string, null: false, default: "created"
    # If flag lives on credentials:
    add_column :credentials, :is_mobile_wallet_credential, :boolean, null: false, default: false
  end
end
```

**Django:**
```python
operations = [
    migrations.AddField("credentials", "accessgrid_id",
        models.CharField(max_length=64, null=True, unique=True, db_index=True)),
    migrations.AddField("credentials", "state",
        models.CharField(max_length=16, choices=[
            ("created","created"),("active","active"),("suspended","suspended"),
            ("unlink","unlink"),("deleted","deleted")], default="created")),
    migrations.AddField("credentials", "is_mobile_wallet_credential",
        models.BooleanField(default=False)),
]
```

**Sequelize:**
```js
await queryInterface.addColumn('credentials', 'accessgrid_id',
  { type: DataTypes.STRING(64), allowNull: true, unique: true });
await queryInterface.addColumn('credentials', 'state',
  { type: DataTypes.ENUM('created','active','suspended','unlink','deleted'),
    allowNull: false, defaultValue: 'created' });
await queryInterface.addColumn('credentials', 'is_mobile_wallet_credential',
  { type: DataTypes.BOOLEAN, allowNull: false, defaultValue: false });
```

**EF Core (C#):** add properties on the entity and run `dotnet ef migrations add AddAccessGrid`.

**GORM (Go):** add struct fields with `gorm:"type:varchar(64);uniqueIndex"`, then `db.AutoMigrate(&Credential{})`.

**Ecto (Elixir):** standard `alter table(:credentials) do add :accessgrid_id, :string ...`.

**Doctrine (PHP/Symfony):** generate via `bin/console make:migration` after adding fields.

## Code to build

### Provisioning

When the host's existing issuance flow produces a credential and `is_mobile_wallet_credential` is true:

1. Pick the right template ID by platform (caller's device or operator choice).
2. Call the SDK: `client.access_cards.provision(card_template_id=..., employee_id=..., full_name=..., email=...)`.
3. Persist the returned `access_pass_id` on the credential as `accessgrid_id`. Set `state = "created"`.
4. Return the `install_url` to the caller (UI presents a button; API returns the URL).

**Idempotency.** Before calling `provision`, check whether the credential already has an `accessgrid_id`. If yes, the operation is a no-op — return the existing install URL via `client.access_cards.get(id)` instead of provisioning again.

### Lifecycle

Map host actions to SDK calls:

| Host action | SDK call | Resulting state |
|-------------|----------|------------------|
| Suspend | `client.access_cards.suspend(id)` | `suspended` |
| Resume | `client.access_cards.resume(id)` | `active` |
| Unlink | `client.access_cards.unlink(id)` | `unlink` |
| Delete | `client.access_cards.delete(id)` | `deleted` |

Do **not** flip `state` locally before the AG call succeeds. Either let the webhook update state (preferred) or update on `200 OK` from the call. Never both — pick one source of truth.

### Webhooks

Subscribe to all `ag.access_pass.*` events plus `ag.webhook.cert_expiring` and `ag.account_balance.low`. See [webhook-events.md](./webhook-events.md) for receiver non-negotiables.

For MVP, create the webhook in the AG console UI and paste the bearer token into env vars. (Essential+ creates webhooks via API and stores tokens in the DB.)

## UI vs API vs both

- **API-only.** Add `POST /credentials/:id/wallet-pass` returning `{ install_url, state }`. Lifecycle as `POST /credentials/:id/wallet-pass/(suspend|resume|unlink)` and `DELETE /credentials/:id/wallet-pass`. Match existing API conventions (REST verbs vs RPC-style action endpoints).
- **UI.** On the credential detail page in the host admin, add a "Send to wallet" button when `is_mobile_wallet_credential` is true and `accessgrid_id IS NULL`. After provisioning, replace with the install URL (QR code + copyable link). Show state from `credentials.state`. Add suspend/resume/unlink/delete buttons gated by state per the transition matrix.
- **Both.** UI calls the same API endpoints.

## Definition of done (MVP)

- [ ] Six secrets loaded; sandbox + prod keys distinguished if applicable.
- [ ] Migration applied to `credentials` (and `credential_formats` if flag lives there).
- [ ] One real credential issued end-to-end on iOS *and* Android. Install confirmed on a real device.
- [ ] Suspend, resume, and delete each tested via UI/API and reflected back via webhook.
- [ ] Replaying the same provisioning trigger does not create a duplicate AG pass.
- [ ] Webhook receiver returns `{"received": true}` with 200 and dedupes by `id`.
- [ ] Cert-expiring and account-balance-low webhooks alert ops (Slack/email/pager — match host conventions).
- [ ] `ACCESSGRID_SECRET_KEY` and `ACCESSGRID_WEBHOOK_BEARER` are not in plaintext anywhere in source control.

## Explicitly NOT in MVP

- Template CRUD via API
- Per-tenant template customization
- Landing pages
- Credential profiles or key management
- Ledger items
- Operator UI for managing AG configuration

If you need any of these, you're at Essential or above. See [integration-essential.md](./integration-essential.md).
