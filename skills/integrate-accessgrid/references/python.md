# Python Patterns

Use this file when the host stack is Python. This is the primary reference and the source of truth that all other language SDKs mirror.

## Install

```bash
pip install accessgrid
```

Requires Python 3.7+. Pin a version in `requirements.txt` / `pyproject.toml` matching the host's dependency-management convention.

## Official SDK Shape

The README shows:

- `AccessGrid(account_id, secret_key)` as the client constructor
- `client.access_cards` — provision, update, list, get, suspend, resume, unlink, delete
- `client.console` — templates, landing pages, webhooks, credential profiles, HID organizations, ledger, event logs
- `client.console.credential_profiles` — list, create profiles
- `client.console.webhooks` — create, list, delete webhooks
- `client.console.hid.orgs` — create, activate, list HID organizations

## Authentication

The docs define request auth with:

- `X-ACCT-ID`
- `X-PAYLOAD-SIG`

The SDK handles this for you when initialized with account credentials.

```python
from accessgrid import AccessGrid

account_id = os.environ.get("ACCOUNT_ID")
secret_key = os.environ.get("SECRET_KEY")

client = AccessGrid(account_id, secret_key)
```

If the host app must make raw HTTP requests for an unsupported endpoint, keep the signing code isolated in one adapter and preserve the same header names.

## Access Pass Provisioning

The README uses `client.access_cards.provision(...)` and shows a rich provisioning payload.

```python
response = client.access_cards.provision(
    card_template_id="0xd3adb00b5",
    employee_id="123456789",
    site_code=credential.site_code,
    card_number=credential.card_number,
    full_name=credential.full_name,
    email=credential.email,
    phone_number=credential.phone_number,
    classification=credential.classification,
    metadata={"pacs_credential_id": str(credential.id)},
)
```

For raw-byte credentials, switch to the documented byte payload form instead of `site_code` and `card_number`.

Wrap this in a host-owned service:

```python
class AccessGridService:
    def __init__(self, client, logger):
        self.client = client
        self.logger = logger

    def provision_access_pass(self, credential):
        self.logger.info(
            "accessgrid.provision.start",
            extra={"pacs_credential_id": credential.id},
        )
        response = self.client.access_cards.provision(
            full_name=credential.full_name,
            metadata={"pacs_credential_id": str(credential.id)},
            site_code=credential.site_code,
            card_number=credential.card_number,
        )
        self.logger.info(
            "accessgrid.provision.success",
            extra={
                "pacs_credential_id": credential.id,
                "accessgrid_card_id": response["id"],
            },
        )
        return response
```

## Lifecycle Operations

The README shows:

```python
client.access_cards.suspend(card_id="0xc4rd1d")
client.access_cards.resume(card_id="0xc4rd1d")
client.access_cards.unlink(card_id="0xc4rd1d")
client.access_cards.delete(card_id="0xc4rd1d")
```

Persist the returned AccessGrid card ID on the host credential before wiring suspend, resume, or delete.

## Idempotent Sync Job

```python
def sync_credential_to_accessgrid(
    credential_id: str,
    source_event_id: str | None,
    credentials_repo,
    sync_attempts_repo,
    accessgrid_service,
):
    credential = credentials_repo.get_for_sync(credential_id)
    dedupe_key = source_event_id or (
        f"credential:{credential.tenant_id}:{credential.id}:provision"
    )

    existing_attempt = sync_attempts_repo.find_by_key(dedupe_key)
    if existing_attempt and existing_attempt.status == "succeeded":
        return existing_attempt.result

    if credential.accessgrid_card_id:
        return accessgrid_service.resume_or_reconcile(credential)

    sync_attempts_repo.mark_started(dedupe_key, credential.id)

    try:
        response = accessgrid_service.provision_access_pass(credential)
        credentials_repo.attach_accessgrid_id(credential.id, response["id"])
        sync_attempts_repo.mark_succeeded(dedupe_key, response["id"])
        return response
    except Exception as exc:
        sync_attempts_repo.mark_failed(dedupe_key, str(exc))
        raise
```

## Console Resources

The README explicitly shows template and event-log methods:

```python
template = client.console.create_template(
    name="Employee Access Pass",
    platform="apple",
    use_case="corporate_id",
    protocol="desfire",
)

events = client.console.event_log(
    card_template_id="0xd3adb00b5",
    filters={"event_type": "install"},
)
```

Do not assume Python console webhook helpers exist unless you confirm them in the live docs or package source; the README excerpt I verified does not show them.

## Webhook Handling

Webhooks arrive as CloudEvents 1.0 payloads. See [webhook-events.md](./webhook-events.md) for the full envelope and event catalog. Receiver must:

1. Verify bearer token from the `Authorization` header against the stored `webhooks.bearer_token` (or env var for MVP).
2. Validate envelope: `payload["specversion"] == "1.0"` and `payload["source"] == "accessgrid"`.
3. Dedupe by `payload["id"]`.
4. Return `{"received": True}` with HTTP 200 always — even on duplicates and unknown event types.

```python
from flask import Flask, request, jsonify
import os, json

app = Flask(__name__)

@app.route("/webhooks/accessgrid", methods=["POST"])
def handle_accessgrid_webhook(webhook_events_repo, credentials_repo):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != os.environ["ACCESSGRID_WEBHOOK_BEARER"]:
        return ("", 401)

    event = request.get_json()
    if event.get("specversion") != "1.0" or event.get("source") != "accessgrid":
        return ("", 400)

    if webhook_events_repo.has_processed(event["id"]):
        return jsonify(received=True)

    webhook_events_repo.mark_received(event["id"], event["type"])

    data = event.get("data") or {}
    accessgrid_id = data.get("access_pass_id")
    etype = event["type"]

    if etype == "ag.access_pass.activated":
        credentials_repo.set_state_by_accessgrid_id(accessgrid_id, "active")
    elif etype == "ag.access_pass.suspended":
        credentials_repo.set_state_by_accessgrid_id(accessgrid_id, "suspended")
    elif etype == "ag.access_pass.resumed":
        credentials_repo.set_state_by_accessgrid_id(accessgrid_id, "active")
    elif etype == "ag.access_pass.unlinked":
        credentials_repo.set_state_by_accessgrid_id(accessgrid_id, "unlink")
    elif etype == "ag.access_pass.deleted":
        credentials_repo.set_state_by_accessgrid_id(accessgrid_id, "deleted")
    # Unknown event types fall through — still ack 200.

    webhook_events_repo.mark_processed(event["id"])
    return jsonify(received=True)
```

## Rate Limits

Docs call out Google Wallet issuer limits. Treat `429` as retryable, respect `Retry-After`, and batch carefully during large rollouts or backfills.

## Tests

```python
def test_replayed_event_does_not_provision_twice(sync_service, mock_client):
    sync_service.sync_credential_to_accessgrid("cred_123", "evt_1")
    sync_service.sync_credential_to_accessgrid("cred_123", "evt_1")

    assert mock_client.access_cards.provision.call_count == 1


def test_duplicate_webhook_event_is_ignored(webhook_sender, webhook_events_repo):
    response = webhook_sender.send({"id": "evt_1", "type": "credential.resumed"})
    response = webhook_sender.send({"id": "evt_1", "type": "credential.resumed"})

    assert response["duplicate"] is True
```
