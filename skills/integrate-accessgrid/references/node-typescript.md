# Node TypeScript Patterns

Use this file when the host stack is Node.js or TypeScript.

## Official SDK Shape

The README shows:

- `new AccessGrid(accountId, secretKey)`
- `client.accessCards` for access-card lifecycle work
- `client.console` for enterprise console features

```ts
const client = new AccessGrid(process.env.ACCOUNT_ID!, process.env.SECRET_KEY!);
```

The SDK should own `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Access Pass Provisioning

```ts
const card = await client.accessCards.provision({
  card_template_id: "0xd3adb00b5",
  employee_id: "123456789",
  full_name: credential.fullName,
  metadata: { pacs_credential_id: String(credential.id) },
  site_code: credential.siteCode,
  card_number: credential.cardNumber,
  email: credential.email,
  phone_number: credential.phoneNumber,
  classification: credential.classification,
});
```

## Lifecycle Operations

The JS README excerpt I verified did not show suspend/resume/delete examples. Confirm exact method names in the package source or live docs before using them.

## Console Resources

```ts
const webhook = await client.console.createWebhook({
  name: "Prod Webhook",
  target_url: "https://host.example.com/webhooks/accessgrid",
});
```

## Webhook Handling

The JS README does show a receiver example using `CloudEventReceiver` and a webhook `private_key`. Use that pattern instead of inventing your own verifier.

```ts
export async function handleAccessGridWebhook(request: Request) {
  const body = await request.text();
  const receiver = new CloudEventReceiver(process.env.ACCESSGRID_WEBHOOK_PRIVATE_KEY!);
  const event = receiver.receive(body);
  if (await webhookEventsRepo.hasProcessed(event.id)) {
    return Response.json({ ok: true, duplicate: true });
  }

  await webhookEventsRepo.markReceived(event.id, event.type);

  switch (event.type) {
    case "credential.suspended":
      await credentialsRepo.markSuspendedByAccessGrid(event.data.metadata.pacs_credential_id);
      break;
    case "credential.resumed":
      await credentialsRepo.markActiveByAccessGrid(event.data.metadata.pacs_credential_id);
      break;
    default:
      await webhookEventsRepo.markIgnored(event.id);
  }

  await webhookEventsRepo.markProcessed(event.id);
  return Response.json({ ok: true });
}
```
