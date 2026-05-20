# Node / TypeScript Patterns

Use this file when the host stack is Node.js or TypeScript.

## Install

```bash
npm install accessgrid
# or
yarn add accessgrid
```

Requires Node.js 12 or higher. Pin via `package.json`.

## Client

```ts
import AccessGrid from 'accessgrid';

const client = new AccessGrid(process.env.ACCOUNT_ID!, process.env.SECRET_KEY!);
```

The SDK owns `X-ACCT-ID` / `X-PAYLOAD-SIG` signing.

## Access Pass Provisioning

```ts
const card = await client.accessCards.provision({
  cardTemplateId: '0xd3adb00b5',
  employeeId: '123456789',
  fullName: credential.fullName,
  email: credential.email,
  tagId: 'DDEADB33FB00B5',
  metadata: { pacs_credential_id: String(credential.id) },
});

console.log(`Install URL: ${card.url}`);
```

## Lifecycle Operations

```ts
await client.accessCards.suspend(accessgridId);
await client.accessCards.resume(accessgridId);
await client.accessCards.unlink(accessgridId);
await client.accessCards.delete(accessgridId);
```

If a method name above differs in the installed SDK version, the README at https://github.com/Access-Grid/accessgrid-js is authoritative.

## Webhook receiver (Express)

```ts
import express from 'express';

const app = express();
app.use(express.json({ type: 'application/cloudevents+json' }));

app.post('/webhooks/accessgrid', async (req, res) => {
  const auth = req.header('Authorization') ?? '';
  if (auth !== `Bearer ${process.env.ACCESSGRID_WEBHOOK_BEARER}`) {
    return res.status(401).end();
  }

  const event = req.body;
  if (event?.specversion !== '1.0' || event?.source !== 'accessgrid') {
    return res.status(400).end();
  }

  if (await webhookEventsRepo.hasProcessed(event.id)) {
    return res.json({ received: true });
  }
  await webhookEventsRepo.markReceived(event.id, event.type);

  const accessgridId = event.data?.access_pass_id;
  switch (event.type) {
    case 'ag.access_pass.activated':
      await credentialsRepo.setStateByAccessgridId(accessgridId, 'active'); break;
    case 'ag.access_pass.suspended':
      await credentialsRepo.setStateByAccessgridId(accessgridId, 'suspended'); break;
    case 'ag.access_pass.resumed':
      await credentialsRepo.setStateByAccessgridId(accessgridId, 'active'); break;
    case 'ag.access_pass.unlinked':
      await credentialsRepo.setStateByAccessgridId(accessgridId, 'unlink'); break;
    case 'ag.access_pass.deleted':
      await credentialsRepo.setStateByAccessgridId(accessgridId, 'deleted'); break;
    // Unknown types fall through — always ack 200.
  }

  await webhookEventsRepo.markProcessed(event.id);
  res.json({ received: true });
});
```

See [webhook-events.md](./webhook-events.md) for the full event catalog.
