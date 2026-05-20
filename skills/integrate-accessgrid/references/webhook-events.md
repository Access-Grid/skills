# AccessGrid Webhook Events

Source: https://accessgrid.com/docs/webhook

Snapshot taken 2026-05-19. Re-fetch if AccessGrid changes the event catalog or transport.

## Transport

- **Format**: CloudEvents 1.0 over HTTPS POST.
- **Content-Type**: `application/cloudevents+json`
- **User-Agent**: `AccessGrid-Webhooks/1.0`
- **Auth**: Bearer token (default) OR mTLS. Bearer token is generated when the webhook is created on AccessGrid (`webhook.private_key` in the create response). mTLS is for hosts that require certificate-based ingress.
- **Retry**: AG retries non-`200/201` responses for **up to 6 hours**, then drops the delivery. Plan for at-least-once, not exactly-once.
- **Expected response body**: `{"received": true}` with HTTP `200` or `201`.

## CloudEvents envelope (every event)

| Field | Type | Notes |
|-------|------|-------|
| `specversion` | string | Always `"1.0"` |
| `id` | string | **Unique event ID — use this for dedupe** |
| `source` | string | Always `"accessgrid"` |
| `type` | string | Event name, e.g. `ag.access_pass.issued` |
| `datacontenttype` | string | Always `"application/json"` |
| `time` | string | ISO 8601 timestamp |
| `data` | object | Event-specific payload (see below) |

## Event catalog and data fields

### Access Pass

| Event | Data fields | Drives host action |
|-------|-------------|---------------------|
| `ag.access_pass.issued` | `access_pass_id`, `protocol`, `card_number`, `site_code`, `file_data`, `metadata` | Set `state=created`, store `accessgrid_id` |
| `ag.access_pass.activated` | `access_pass_id`, `device`, `protocol`, `metadata` | Set `state=active` |
| `ag.access_pass.updated` | `access_pass_id`, `protocol`, `metadata` | Refresh metadata if mirrored |
| `ag.access_pass.suspended` | `access_pass_id`, `protocol`, `metadata` | Set `state=suspended` |
| `ag.access_pass.resumed` | `access_pass_id`, `protocol`, `metadata` | Set `state=active` |
| `ag.access_pass.unlinked` | `access_pass_id`, `protocol`, `metadata` | Set `state=unlink` |
| `ag.access_pass.deleted` | `access_pass_id`, `protocol`, `metadata` | Set `state=deleted` (terminal) |
| `ag.access_pass.expired` | `access_pass_id`, `protocol`, `metadata` | App-specific; commonly `suspended` |
| `ag.access_pass.renewed` | `access_pass_id`, `protocol`, `metadata` | Set `state=active`; bump expiration |
| `ag.access_pass.failed` | `access_pass_id`, `protocol`, `metadata` | Alert on; do not change state |
| `ag.access_pass.devices.added` | `access_pass_id`, `device`, `protocol` | Append to device log |
| `ag.access_pass.devices.suspended` | `access_pass_id`, `device`, `protocol` | Device-level suspend |
| `ag.access_pass.devices.resumed` | `access_pass_id`, `device`, `protocol` | Device-level resume |
| `ag.access_pass.devices.removed` | `access_pass_id`, `device`, `protocol` | Device removed from pass |
| `ag.access_pass.viewed` | `access_pass_id`, … | Useful for engagement logs |

`device` is `{ "type": ..., "id": ... }`. `protocol` is `desfire`, `seos`, or `smart_tap`.

### Card Template

| Event | Data fields |
|-------|-------------|
| `ag.card_template.created` | `card_template_id`, `protocol`, `metadata` |
| `ag.card_template.updated` | `card_template_id`, `protocol`, `metadata` |
| `ag.card_template.requested_publishing` | `card_template_id`, `protocol`, `metadata` |
| `ag.card_template.published` | `card_template_id`, `protocol`, `metadata` |
| `ag.card_template.deleted` | `card_template_id`, `protocol`, `metadata` |

### Landing Page

| Event | Data fields |
|-------|-------------|
| `ag.landing_page.created` | `landing_page_id` |
| `ag.landing_page.updated` | `landing_page_id` |
| `ag.landing_page.attached_to_template` | `landing_page_id` |

### Credential Profile

| Event | Data fields |
|-------|-------------|
| `ag.credential_profile.created` | `credential_profile_id` |
| `ag.credential_profile.attached_to_template` | `credential_profile_id` |

### Webhook / Account

| Event | Data fields | Operational meaning |
|-------|-------------|----------------------|
| `ag.webhook.cert_expiring` | none documented | Rotate mTLS cert; update `client_certificate_expiration_date` |
| `ag.account_balance.low` | `account_id`, `organization_name`, `current_balance`, `threshold`, `amount_below_threshold` | Alert ops; pause non-essential issuance |
| `ag.account.impersonation_started` | … | Audit log entry |
| `ag.account.impersonation_ended` | … | Audit log entry |

## Recommended subscriptions per integration level

| Integration level | Subscribe to |
|-------------------|---------------|
| **MVP** | All `ag.access_pass.*` events + `ag.webhook.cert_expiring` + `ag.account_balance.low` |
| **Essential** | MVP set + all `ag.card_template.*` events |
| **Complete** | Essential set + all `ag.credential_profile.*` events |
| **Premium** | Complete set + all `ag.landing_page.*` events + `ag.account.impersonation_*` |

You can subscribe to more than you handle — unknown event types should be logged and `200`-acked, not 500'd.

## Receiver non-negotiables

1. **Verify the bearer token** (or mTLS cert) on every request before parsing the body. Reject 401 otherwise.
2. **Validate envelope shape**: `payload.specversion == "1.0"` and `payload.source == "accessgrid"`. Reject 400 otherwise.
3. **Dedupe by `id`**. Persist seen IDs (TTL ≥ 7 days). Drop on second sight, still 200-ack.
4. **Handle unknown `type`** by logging and returning 200 — don't crash on a new event the SDK hasn't taught you yet.
5. **Always return `{"received": true}` with 200/201** on successful processing. Any other response triggers up to 6 hours of retries.
6. **Process async** if work might exceed ~5 seconds. Persist the event, enqueue, ack immediately. The processor handles state changes and retries from durable storage.
7. **Idempotent state writes**. Re-applying `ag.access_pass.suspended` on an already-suspended record is a no-op, not an error.

## Endpoint creation (Essential+ via API)

`POST https://api.accessgrid.com/v1/console/webhooks`

```json
{
  "name": "host-app-prod",
  "url": "https://your-host.example.com/webhooks/accessgrid",
  "subscribed_events": ["ag.access_pass.issued", "ag.access_pass.activated", "..."],
  "auth_method": "bearer_token"
}
```

Response includes `webhook.id` and `webhook.private_key`. The private key is the bearer your endpoint will receive — store it encrypted in the `webhooks.bearer_token` column from the Essential migration.

For MVP, you can create the webhook in the AG console UI and paste the bearer into env vars instead of storing in DB.

## Sample receiver skeletons

Live samples for curl, Node/Express, Ruby/Sinatra, Go, Python/Flask, C#/.NET, Java, and PHP/Slim are on https://accessgrid.com/docs/webhook — match the framework conventions in the host codebase rather than copying these verbatim.
