# Ruby On Rails Patterns

Use this file when the host stack is Ruby or Rails.

## Official SDK Shape

The README shows:

- `AccessGrid::Client.new(account_id:, secret_key:)`
- `client.access_cards` for access-card lifecycle work
- `client.console` for enterprise console features

```rb
client = AccessGrid::Client.new(
  account_id: ENV.fetch("ACCOUNT_ID"),
  secret_key: ENV.fetch("SECRET_KEY")
)
```

The SDK should own `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Access Pass Provisioning

```rb
card = client.access_cards.provision(
  card_template_id: "0xd3adb00b5",
  employee_id: "123456789",
  full_name: credential.full_name,
  metadata: { pacs_credential_id: credential.id.to_s },
  site_code: credential.site_code,
  card_number: credential.card_number,
  email: credential.email,
  phone_number: credential.phone_number,
  classification: credential.classification
)
```

## Lifecycle Operations

The Ruby README excerpt I verified did not show suspend/resume/delete examples. Confirm exact method names in the package source or live docs before using them.

## Console Resources

```rb
webhook = client.console.create_webhook(
  name: "Prod Webhook",
  target_url: "https://host.example.com/webhooks/accessgrid"
)
```

## Webhook Handling

The Ruby README excerpt I verified did not show receiver verification code. Build that from the official webhook docs.

```rb
class AccessgridWebhooksController < ApplicationController
  skip_before_action :verify_authenticity_token

  def create
    event = JSON.parse(request.raw_post)
    return head :ok if WebhookEvent.processed?(event.fetch("id"))

    WebhookEvent.mark_received!(event.fetch("id"), event.fetch("type"))

    pacs_credential_id = event.dig("data", "metadata", "pacs_credential_id")
    case event.fetch("type")
    when "credential.suspended"
      Credential.find(pacs_credential_id).update!(status: "suspended")
    when "credential.resumed"
      Credential.find(pacs_credential_id).update!(status: "active")
    else
      WebhookEvent.mark_ignored!(event.fetch("id"))
    end

    WebhookEvent.mark_processed!(event.fetch("id"))
    head :ok
  end
end
```
