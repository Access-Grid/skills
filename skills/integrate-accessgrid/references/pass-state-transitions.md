# AccessGrid Pass State Transitions

Source: https://accessgrid.com/guides/knowledgebase/how-the-state-transitions-work-for-passes-on-accessgrid

Snapshot taken 2026-05-19. Re-fetch if AccessGrid changes the state machine.

## States

A pass exists in exactly one of five states:

- `created` — initial state, set when a Card ID is created during provisioning
- `active` — pass has been installed to Apple or Google Wallet
- `suspended` — temporarily disabled (API-initiated or device marked lost)
- `unlink` — disabled on-device, original install URL no longer works
- `deleted` — terminal; pass is removed from all devices and cannot transition further

## Transition Matrix

| From | To | Trigger |
|------|------|---------|
| `created` | `active` | User completes wallet install |
| `created` | `deleted` | API consumer deletes |
| `active` | `suspended` | API consumer suspends OR device marked lost |
| `active` | `unlink` | API consumer unlinks |
| `active` | `deleted` | API consumer deletes |
| `suspended` | `active` | API consumer resumes OR device marked found |
| `suspended` | `unlink` | API consumer unlinks |
| `suspended` | `deleted` | API consumer deletes |
| `unlink` | `deleted` | API consumer deletes |

## Hard Rules

- Only `active` passes can be suspended. Suspending a non-active pass returns `can not manage a pass that is not active`.
- Resume targets `active` and is only valid from `suspended` or `unlink`.
- `unlink` disables the pass on-device and prevents reinstallation from the original URL — use it for revocation that should still keep the AG record.
- `deleted` is terminal. Do not model "undeleted" in the host app.

## Host-side `state` enum recommendation

Mirror the AG state names verbatim in the host `credentials.state` column (or your equivalent). The webhook event names below already align:

| AG Event | Resulting host state |
|----------|-----------------------|
| `ag.access_pass.issued` | `created` |
| `ag.access_pass.activated` | `active` |
| `ag.access_pass.suspended` | `suspended` |
| `ag.access_pass.resumed` | `active` |
| `ag.access_pass.unlinked` | `unlink` |
| `ag.access_pass.deleted` | `deleted` |
| `ag.access_pass.failed` | leave state unchanged; raise alert |
| `ag.access_pass.expired` | `suspended` (recommended) or app-specific |
| `ag.access_pass.renewed` | `active` |

For the full event → action mapping, see [webhook-events.md](./webhook-events.md).
