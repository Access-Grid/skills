# Database Discovery — Mapping the Host Schema

Before any migration is written, you must locate (or help create) the four canonical concepts AccessGrid binds to. Do **not** invent table names — find the existing ones, then confirm with the user using the prompt pattern below.

## The four canonical concepts

| Concept | What you're looking for | Typical names |
|---------|--------------------------|---------------|
| **Credential Holders** | People the credentials are issued to. First name, last name, email; often a foreign-key target for credentials, devices, audit. | `users`, `people`, `identities`, `members`, `cardholders`, `employees` |
| **Credentials** | The actual access card / pass. FK to credential holder, has site code and/or card number, and a state/status. | `credentials`, `cards`, `access_cards`, `passes`, `badges` |
| **Credential Formats** | Bit format definition: bits, parity bits, separators, facility code layout. May span multiple tables (e.g., `formats` + `format_fields`). | `card_formats`, `credential_formats`, `bit_formats`, `formats` |
| **Event Logs** | Audit/event trail of actions in the system. | `events`, `audit_logs`, `event_logs`, `activities`, `access_events` |

## Discovery procedure

1. **Read the schema.** If the user has an ERD, schema dump, or ORM model file (Rails `schema.rb`, Django `models.py`, Sequelize migrations, Prisma `schema.prisma`, EF migrations, Ecto schemas), read it directly. Otherwise ask for one or run `\dt` / `SHOW TABLES` against the dev DB.
2. **Tag candidates.** For each canonical concept, list the 1–3 most likely tables based on naming AND the columns expected (e.g., a `users` table without site-code-like columns is probably the Credential Holders match, not the Credentials match).
3. **Confirm with the user — one question per concept.** Use the exact pattern:

   > "Which table best represents the idea of **Credential Holders** in your existing system?
   > A. `users`
   > B. `identities`
   > C. `people`
   > D. Something else (type it)"

   Wait for an answer before moving to the next concept. Do not batch all four into one question — operators need to think.
4. **Internalize and persist.** Once confirmed, record the choices in the mapping doc maintained in the host repo (see SKILL.md Phase 3) so later phases can refer back without re-asking.

## When a concept doesn't exist

All four are required even for MVP. If a concept is missing, walk the user through creating it before any AG migration runs:

- **No Credential Holders table** — extremely rare; if true, surface that we can't proceed until the host has a user model. This is a product gap, not a migration.
- **No Credentials table** — common in greenfield setups. Help design a minimal one: `id`, `credential_holder_id` (FK), `site_code`, `card_number`, `state`, timestamps. Add the AccessGrid columns from the general migration (see [integration-mvp.md](./integration-mvp.md)) in the same migration to avoid two passes.
- **No Credential Formats table** — also common. Design `id`, `name`, `bits`, `parity_bits`, `separators` (or whatever shape fits the protocols in play). Block on this: format is what drives card-template selection in Essential+.
- **No Event Logs table** — propose either reusing an existing audit/notification system or creating one with `id`, `event_type`, `subject_type`, `subject_id`, `payload` (JSONB), `occurred_at`.

In all cases, write the new tables in the host project's existing migration style (Rails generator, Django `manage.py makemigrations`, Knex, EF migrations, etc.) — don't introduce a new tooling pattern.

## Where the AG flag lives

You must ask explicitly: **"Should the 'is mobile wallet credential' flag live on the Credential Formats table or the Credentials table?"**

- **On Credential Formats** — appropriate if mobile-wallet eligibility is a property of the format itself (a given bit format is or isn't mobile-eligible). One-time decision per format.
- **On Credentials** — appropriate if individual credentials can be either physical or mobile under the same format. Per-row decision.

Both are valid. The migration columns in [integration-mvp.md](./integration-mvp.md) get added to whichever table the user picks. Record the choice in the mapping doc.

## What gets added to Credentials regardless of where the flag lives

Even if the flag is on Credential Formats, the AccessGrid-specific columns still belong on the **Credentials** table (one AG record per credential):

- `is_mobile_wallet_credential` (boolean) — only here if the user chose the per-credential placement
- `accessgrid_id` (string, indexed, nullable) — the AG `access_pass_id` returned at provision time
- `state` (enum: `created`, `active`, `suspended`, `unlink`, `deleted`) — mirrors AG; see [pass-state-transitions.md](./pass-state-transitions.md)

If the user chose to put the flag on Credential Formats, only the `accessgrid_id` and `state` columns are added to Credentials.

## Backfill consideration

If the host already has many existing Credentials, ask whether they want to:

1. Leave existing rows null/`accessgrid_id IS NULL` and only provision on **next** lifecycle event, or
2. Run a one-time backfill job that provisions every eligible existing credential to AG.

Option 1 is safer for production rollout. Option 2 needs a rate-limit-aware job; the AG SDK's pagination + your queue infrastructure handle this. Record the choice in the mapping doc.
