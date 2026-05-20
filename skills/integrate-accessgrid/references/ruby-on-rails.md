# Ruby / Rails Patterns

Use this file when the host stack is Rails (or any Ruby app).

## Install

```ruby
# Gemfile
gem 'accessgrid'
```

```bash
bundle install
# or, outside Bundler:
gem install accessgrid
```

Requires Ruby 2.19 or higher.

## Client

```ruby
require 'accessgrid'

client = AccessGrid.new(ENV.fetch('ACCOUNT_ID'), ENV.fetch('SECRET_KEY'))
```

Wrap in a host-owned service object (idiomatic Rails) instead of using the raw client directly from controllers.

## Provisioning

```ruby
card = client.access_cards.issue(
  card_template_id: template.accessgrid_id,
  employee_id: credential.holder.external_id,
  tag_id: credential.card_number,
  full_name: credential.holder.full_name,
  email: credential.holder.email,
  metadata: { pacs_credential_id: credential.id.to_s }
)

credential.update!(accessgrid_id: card.id, state: 'created')
```

## Lifecycle

```ruby
client.access_cards.suspend(credential.accessgrid_id)
client.access_cards.resume(credential.accessgrid_id)
client.access_cards.unlink(credential.accessgrid_id)
client.access_cards.delete(credential.accessgrid_id)
```

Confirm method names against the installed gem version — README at https://github.com/Access-Grid/accessgrid-rb is authoritative.

## Webhook receiver (Rails controller)

```ruby
class AccessgridWebhooksController < ActionController::API
  def create
    bearer = request.headers['Authorization'].to_s.delete_prefix('Bearer ')
    head :unauthorized unless ActiveSupport::SecurityUtils.secure_compare(
      bearer, Rails.application.credentials.accessgrid_webhook_bearer
    )

    event = JSON.parse(request.raw_post)
    return head :bad_request unless event['specversion'] == '1.0' && event['source'] == 'accessgrid'

    if WebhookEvent.exists?(accessgrid_event_id: event['id'])
      return render json: { received: true }
    end

    ApplicationRecord.transaction do
      WebhookEvent.create!(accessgrid_event_id: event['id'], event_type: event['type'])
      apply_event(event)
    end

    render json: { received: true }
  end

  private

  def apply_event(event)
    accessgrid_id = event.dig('data', 'access_pass_id')
    case event['type']
    when 'ag.access_pass.activated' then Credential.find_by(accessgrid_id:)&.update!(state: 'active')
    when 'ag.access_pass.suspended' then Credential.find_by(accessgrid_id:)&.update!(state: 'suspended')
    when 'ag.access_pass.resumed'   then Credential.find_by(accessgrid_id:)&.update!(state: 'active')
    when 'ag.access_pass.unlinked'  then Credential.find_by(accessgrid_id:)&.update!(state: 'unlink')
    when 'ag.access_pass.deleted'   then Credential.find_by(accessgrid_id:)&.update!(state: 'deleted')
    # Unknown types are recorded and ignored.
    end
  end
end
```

Skip CSRF for the webhook route. Use `ActiveSupport::SecurityUtils.secure_compare` to avoid timing attacks on the bearer.

## Encryption-at-rest

Use built-in ActiveRecord encryption (Rails 7+):

```ruby
class Webhook < ApplicationRecord
  encrypts :bearer_token
end

class CredentialProfileKey < ApplicationRecord
  encrypts :key_value
end
```

Set up `bin/rails db:encryption:init` and store keys in `Rails.application.credentials`.

## Background jobs

Use ActiveJob for any AG call that runs in response to a user-facing request — provisioning, especially. The HTTP round-trip can exceed acceptable web-response latency.

```ruby
class ProvisionAccessgridPassJob < ApplicationJob
  queue_as :default
  retry_on Net::OpenTimeout, wait: :exponentially_longer, attempts: 5
  discard_on AccessGrid::ClientError # 4xx — no point retrying
end
```
