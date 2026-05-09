# Laravel PHP Patterns

Use this file when the host stack is Laravel or PHP.

## Official SDK Shape

The README shows:

- `new AccessGrid($accountId, $secretKey)`
- `$client->accessCards()` for access-card lifecycle work
- `$client->console()` for enterprise console features

```php
$client = new AccessGrid(
    $_ENV['ACCOUNT_ID'],
    $_ENV['SECRET_KEY'],
);
```

The SDK should own `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Access Pass Provisioning

```php
$card = $client->accessCards()->provision([
    'card_template_id' => '0xd3adb00b5',
    'employee_id' => '123456789',
    'full_name' => $credential->full_name,
    'metadata' => [
        'pacs_credential_id' => (string) $credential->id,
    ],
    'site_code' => $credential->site_code,
    'card_number' => $credential->card_number,
    'email' => $credential->email,
    'phone_number' => $credential->phone_number,
    'classification' => $credential->classification,
]);
```

## Lifecycle Operations

The PHP README excerpt I verified did not show suspend/resume/delete examples. Confirm exact method names in the package source or live docs before using them.

## Console Resources

```php
$webhook = $client->console()->createWebhook([
    'name' => 'Prod Webhook',
    'target_url' => 'https://host.example.com/webhooks/accessgrid',
]);
```

## Webhook Handling

The PHP README excerpt I verified did not show receiver verification code. Build that from the official webhook docs.

```php
class AccessGridWebhookController extends Controller
{
    public function __invoke(Request $request, WebhookEventsRepository $events, CredentialsRepository $credentials)
    {
        $event = $request->json()->all();
        if ($events->hasProcessed($event['id'])) {
            return response()->json(['ok' => true, 'duplicate' => true]);
        }

        $events->markReceived($event['id'], $event['type']);

        $credentialId = $event['data']['metadata']['pacs_credential_id'];
        if ($event['type'] === 'credential.suspended') {
            $credentials->markSuspendedByAccessGrid($credentialId);
        } elseif ($event['type'] === 'credential.resumed') {
            $credentials->markActiveByAccessGrid($credentialId);
        } else {
            $events->markIgnored($event['id']);
        }

        $events->markProcessed($event['id']);
        return response()->json(['ok' => true]);
    }
}
```
