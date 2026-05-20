# Laravel / PHP Patterns

Use this file when the host stack is Laravel or any modern PHP framework.

## Install

```bash
composer require accessgrid/accessgrid-php
```

Requires PHP 7.4 or higher.

## Client

```php
use AccessGrid\Client;

$client = new Client($_ENV['ACCOUNT_ID'], $_ENV['SECRET_KEY']);
```

In Laravel, bind as a singleton in a service provider:

```php
$this->app->singleton(Client::class, fn () => new Client(
    config('services.accessgrid.account_id'),
    config('services.accessgrid.secret_key'),
));
```

The SDK owns `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Provisioning

```php
$card = $client->accessCards->provision([
    'card_template_id' => $template->accessgrid_id,
    'employee_id'      => $credential->holder->external_id,
    'tag_id'           => $credential->card_number,
    'full_name'        => $credential->holder->full_name,
    'email'            => $credential->holder->email,
    'metadata'         => ['pacs_credential_id' => (string) $credential->id],
]);

$credential->update([
    'accessgrid_id' => $card->id,
    'state'         => 'created',
]);
```

## Lifecycle

```php
$client->accessCards->suspend($accessgridId);
$client->accessCards->resume($accessgridId);
$client->accessCards->unlink($accessgridId);
$client->accessCards->delete($accessgridId);
```

Confirm method names against the installed Composer version.

## Webhook receiver (Laravel)

```php
class AccessGridWebhookController extends Controller
{
    public function __invoke(Request $request, WebhookEventsRepository $events, CredentialsRepository $credentials)
    {
        $bearer = $request->bearerToken();
        if (! hash_equals(config('services.accessgrid.webhook_bearer'), (string) $bearer)) {
            abort(401);
        }

        $event = $request->json()->all();
        if (($event['specversion'] ?? null) !== '1.0' || ($event['source'] ?? null) !== 'accessgrid') {
            abort(400);
        }

        if ($events->hasProcessed($event['id'])) {
            return response()->json(['received' => true]);
        }
        $events->markReceived($event['id'], $event['type']);

        $accessgridId = $event['data']['access_pass_id'] ?? null;

        match ($event['type']) {
            'ag.access_pass.activated' => $credentials->setStateByAccessGridId($accessgridId, 'active'),
            'ag.access_pass.suspended' => $credentials->setStateByAccessGridId($accessgridId, 'suspended'),
            'ag.access_pass.resumed'   => $credentials->setStateByAccessGridId($accessgridId, 'active'),
            'ag.access_pass.unlinked'  => $credentials->setStateByAccessGridId($accessgridId, 'unlink'),
            'ag.access_pass.deleted'   => $credentials->setStateByAccessGridId($accessgridId, 'deleted'),
            default => null, // Unknown types fall through.
        };

        $events->markProcessed($event['id']);
        return response()->json(['received' => true]);
    }
}
```

Exclude the webhook route from CSRF in `VerifyCsrfToken::$except`. Use `hash_equals` for the bearer comparison to avoid timing attacks.

See [webhook-events.md](./webhook-events.md) for the full event catalog.

## Encryption-at-rest

Laravel 10+ supports the `encrypted` cast natively:

```php
class Webhook extends Model
{
    protected $casts = ['bearer_token' => 'encrypted'];
}

class CredentialProfileKey extends Model
{
    protected $casts = ['key_value' => 'encrypted'];
}
```

For non-Laravel PHP apps, use Halite (libsodium wrapper) or PHP's `sodium_*` functions with a key from your KMS.

## Background jobs

Use Laravel queues for provisioning to keep web requests fast:

```php
ProvisionAccessGridPassJob::dispatch($credential->id);
```

Mark the job `ShouldQueue`, configure `tries = 5`, and `backoff()` with exponential delays. Catch 4xx errors and fail the job permanently instead of retrying.
