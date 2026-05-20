# Complete Integration

**Scope.** Everything in [Essential](./integration-essential.md), plus **fully editable card templates with branding**, **credential profiles with key management**, **device policies**, and a **host-app operator UI for managing all of it**. This is what a customer-facing dashboard looks like.

**When this is the right level.** The host product offers self-serve template management to its own end-customers, or the host org needs to manage many credential profiles and key sets across products/sites without going to the AG console.

## What carries over from Essential

- All MVP and Essential migrations and code paths.
- Webhook receiver now subscribes to `ag.credential_profile.*` in addition to the Essential set.

## Migration additions

### Extensions to `card_templates` (Essential's table)

Add branding columns:

| Column | Type | Notes |
|--------|------|-------|
| `logo` | image (attachment / blob / S3 ref) | Validate dimensions per [image-dimensions.md](./image-dimensions.md) |
| `background` | image | Same |
| `icon` | image | Same |
| `background_color` | string | Hex, validated (`#RRGGBB` or `#RRGGBBAA`) |
| `label_color` | string | Hex |
| `secondary_color` | string | Hex |

Use the host's standard file-attachment story (ActiveStorage, django-storages + S3, multer + S3, etc.) — don't introduce a new one.

### New: `credential_profiles`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `name` | string | not null, operator-defined |
| `uses_key_diversification` | boolean | default false |
| timestamps | datetime | not null |

### New: `credential_profile_keys`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `credential_profile_id` | FK | not null, → `credential_profiles.id`, on delete cascade |
| `key_id` | integer | not null |
| `key_value` | **encrypted string** | not null — **MUST** be encrypted at rest using the same mechanism as webhook bearer tokens |
| `use_an10922_diversification` | boolean | default false |
| timestamps | datetime | not null |
| (unique index) | `(credential_profile_id, key_id)` | |

### New: `credential_profile_files`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `credential_profile_id` | FK | not null, → `credential_profiles.id`, on delete cascade |
| `file_id` | integer | not null |
| `file_size` | integer | not null, in bytes |
| timestamps | datetime | not null |
| (unique index) | `(credential_profile_id, file_id)` | |

### New: `card_template_bundles`

Groups one iOS, one Android, and one Samsung template into a single "bundle" the host references at issuance time.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `name` | string | not null |
| `ios_template_id` | FK | nullable, → `card_templates.id` |
| `android_template_id` | FK | nullable, → `card_templates.id` |
| `samsung_template_id` | FK | nullable, → `card_templates.id` |
| timestamps | datetime | not null |

Add a CHECK constraint or ORM validator: at least one of `ios_template_id` / `android_template_id` / `samsung_template_id` must be non-null.

Optionally, replace the Essential `card_template_credential_formats` join with `card_template_bundle_credential_formats` (same shape, swap `card_template_id` for `card_template_bundle_id`) so the runtime selects a bundle, then the platform-appropriate template inside it. Discuss with the user — both are valid, but the bundle-first approach is the canonical Complete pattern.

## Code to build (additions to Essential)

### Provisioning with bundles

When `card_template_bundles` is in play:

1. Look up the credential's format → associated bundles (via the new join).
2. Pick the right bundle (host policy; if there's only one, take it).
3. Within the bundle, pick the column matching the caller's platform (`ios_template_id` / `android_template_id` / `samsung_template_id`).
4. If that column is null, the bundle does not support that platform — return a clear error rather than falling back.
5. Use the resolved template's `accessgrid_id` for `client.access_cards.provision(...)`.

### Credential profile lifecycle

Operator creates a profile, adds keys (with optional AN10922 diversification flag), uploads files. Mirror each step to AccessGrid via `client.console.credential_profiles.*`. Attach the profile to one or more card templates.

**Key handling rules:**
- Keys are written **once** by the operator and never displayed again ("reveal once" UX).
- Decryption only happens in-memory at the moment of an AG API call. Never log key values. Never include them in error messages or webhook payloads.
- Rotating a key creates a new `credential_profile_keys` row with a new `key_id`; the old row stays for audit unless the operator explicitly destroys it.

### Template image validation

Run [image-dimensions.md](./image-dimensions.md) checks at upload time — reject before persisting. Show the operator the expected dimensions for the template's `platform` and `protocol` combination.

### Webhook subscriptions

Add all `ag.credential_profile.*` events to the receiver. Map them:

- `ag.credential_profile.created` → reconcile profile state if created out-of-band
- `ag.credential_profile.attached_to_template` → update host-side association if changed via AG console

## UI requirements

The Complete level explicitly adds a **host-app operator UI**. At minimum:

- **Templates index/detail** — list, filter by platform/protocol, edit branding, upload assets with live preview, link to formats, publish gating.
- **Credential profiles index/detail** — list, create, manage keys (write-once UX with visible-once toast on creation), manage files, attach to templates.
- **Card template bundles index/detail** — list, create, assign per-platform templates, link to formats.
- **Webhooks index/detail** — inherits from Essential.

Use the host's existing admin design system. Do **not** build a separate app for AG.

## Definition of done (Complete)

All Essential checkboxes, **plus**:

- [ ] Card templates support logo/background/icon uploads with platform-appropriate dimension validation.
- [ ] Color fields validate as hex.
- [ ] `credential_profiles` + `credential_profile_keys` + `credential_profile_files` migrations applied.
- [ ] `credential_profile_keys.key_value` encrypted at rest, verified by inspecting raw DB column.
- [ ] Key-value reveal-once UX implemented: operator sees value only at creation; subsequent views show masked value.
- [ ] `card_template_bundles` migration applied with the at-least-one-platform CHECK.
- [ ] Issuance correctly resolves bundle → platform template → AG template ID.
- [ ] Missing-platform-in-bundle path returns a clear, actionable error.
- [ ] Operator UI lists, creates, edits, and (where safe) deletes templates, profiles, bundles, and webhooks.
- [ ] `ag.credential_profile.*` events handled and reconcile out-of-band changes.

## Explicitly NOT in Complete

- Landing pages
- Ledger items

If you need either, you're at Premium. See [integration-premium.md](./integration-premium.md).
