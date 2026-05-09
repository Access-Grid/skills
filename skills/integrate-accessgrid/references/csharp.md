# C# Patterns

Use this file when the host stack is C# or .NET.

## Official SDK Shape

The README shows:

- `new AccessGrid(accountId, secretKey)`
- `_client.AccessCards` for access-card lifecycle work
- `_client.Console` for enterprise console features

```csharp
var client = new AccessGrid(
    Environment.GetEnvironmentVariable("ACCOUNT_ID")!,
    Environment.GetEnvironmentVariable("SECRET_KEY")!
);
```

The SDK should own `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Access Pass Provisioning

```csharp
var payload = new Dictionary<string, object?>
{
    ["card_template_id"] = "0xd3adb00b5",
    ["employee_id"] = "123456789",
    ["full_name"] = credential.FullName,
    ["metadata"] = new Dictionary<string, object?>
    {
        ["pacs_credential_id"] = credential.Id,
    },
    ["site_code"] = credential.SiteCode,
    ["card_number"] = credential.CardNumber,
};

var card = await client.AccessCards.Provision(payload);
```

## Lifecycle Operations

The C# README excerpt I verified did not show suspend/resume/delete examples. Confirm exact method names in the package source or live docs before using them.

## Console Resources

```csharp
var template = await client.Console.CreateTemplate(new CardTemplateInput
{
    Name = "Employee Access Pass",
    Platform = "apple",
    UseCase = "corporate_id",
    Protocol = "desfire"
});
```

## Webhook Handling

The C# README excerpt I verified did not show receiver verification code. Build that from the official webhook docs.

```csharp
[ApiController]
[Route("webhooks/accessgrid")]
public sealed class AccessGridWebhookController : ControllerBase
{
    [HttpPost]
    public async Task<IActionResult> Post(CancellationToken cancellationToken)
    {
        using var reader = new StreamReader(Request.Body);
        var rawBody = await reader.ReadToEndAsync(cancellationToken);
        var eventPayload = JsonSerializer.Deserialize<WebhookEvent>(rawBody)!;

        if (await _webhookEventsRepo.HasProcessedAsync(eventPayload.Id, cancellationToken))
        {
            return Ok(new { ok = true, duplicate = true });
        }

        await _webhookEventsRepo.MarkReceivedAsync(eventPayload.Id, eventPayload.Type, cancellationToken);

        switch (eventPayload.Type)
        {
            case "credential.suspended":
                await _credentialsRepo.MarkSuspendedByAccessGridAsync(
                    eventPayload.Data.Metadata.PACSCredentialId,
                    cancellationToken);
                break;
            case "credential.resumed":
                await _credentialsRepo.MarkActiveByAccessGridAsync(
                    eventPayload.Data.Metadata.PACSCredentialId,
                    cancellationToken);
                break;
            default:
                await _webhookEventsRepo.MarkIgnoredAsync(eventPayload.Id, cancellationToken);
                break;
        }

        await _webhookEventsRepo.MarkProcessedAsync(eventPayload.Id, cancellationToken);
        return Ok(new { ok = true });
    }
}
```
