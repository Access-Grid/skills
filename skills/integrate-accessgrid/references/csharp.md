# C# / .NET Patterns

Use this file when the host stack is C# or .NET.

## Install

```bash
dotnet add package accessgrid --version 1.5.0
```

Bump the version to latest when starting fresh — check https://www.nuget.org/packages/accessgrid.

## Client

```csharp
var client = new AccessGridClient(
    Environment.GetEnvironmentVariable("ACCESSGRID_ACCOUNT_ID")!,
    Environment.GetEnvironmentVariable("ACCESSGRID_SECRET_KEY")!
);
```

**Note:** the .NET SDK reads `ACCESSGRID_ACCOUNT_ID` / `ACCESSGRID_SECRET_KEY` (prefixed) rather than the bare `ACCOUNT_ID` / `SECRET_KEY` used by other SDKs. Match the prefix the host already uses for secrets, or alias env vars consistently in your deployment config.

Authentication wire format: `X-ACCT-ID` (account ID) and `X-PAYLOAD-SIG` (HMAC signature) headers, owned by the SDK.

## Provisioning

```csharp
var card = await client.AccessCards.ProvisionAsync(
    new ProvisionCardRequest
    {
        CardTemplateId = template.AccessGridId,
        EmployeeId     = credential.Holder.ExternalId,
        FullName       = credential.Holder.FullName,
        Email          = credential.Holder.Email,
        StartDate      = DateTime.UtcNow,
        ExpirationDate = DateTime.UtcNow.AddYears(1),
        Metadata       = new Dictionary<string, string>
        {
            ["pacs_credential_id"] = credential.Id.ToString()
        }
    }
);

await credentialsRepo.AttachAccessGridIdAsync(credential.Id, card.Id);
Console.WriteLine($"Install URL: {card.Url}");
```

## Lifecycle

```csharp
await client.AccessCards.SuspendAsync(accessgridId);
await client.AccessCards.ResumeAsync(accessgridId);
await client.AccessCards.UnlinkAsync(accessgridId);
await client.AccessCards.DeleteAsync(accessgridId);
```

Confirm method names against the installed SDK version.

## Webhook receiver (ASP.NET)

```csharp
[ApiController]
[Route("webhooks/accessgrid")]
public sealed class AccessGridWebhookController : ControllerBase
{
    private readonly IConfiguration _config;
    private readonly IWebhookEventsRepository _events;
    private readonly ICredentialsRepository _creds;

    public AccessGridWebhookController(IConfiguration config,
        IWebhookEventsRepository events, ICredentialsRepository creds)
    {
        _config = config; _events = events; _creds = creds;
    }

    [HttpPost]
    [Consumes("application/cloudevents+json")]
    public async Task<IActionResult> Post(CancellationToken ct)
    {
        var auth = Request.Headers.Authorization.ToString();
        var expected = "Bearer " + _config["AccessGrid:WebhookBearer"];
        if (!string.Equals(auth, expected, StringComparison.Ordinal)) return Unauthorized();

        using var reader = new StreamReader(Request.Body);
        var raw = await reader.ReadToEndAsync(ct);
        var ev = JsonSerializer.Deserialize<JsonElement>(raw);

        if (ev.GetProperty("specversion").GetString() != "1.0" ||
            ev.GetProperty("source").GetString() != "accessgrid") return BadRequest();

        var id   = ev.GetProperty("id").GetString()!;
        var type = ev.GetProperty("type").GetString()!;

        if (await _events.HasProcessedAsync(id, ct)) return Ok(new { received = true });
        await _events.MarkReceivedAsync(id, type, ct);

        var accessgridId = ev.TryGetProperty("data", out var data)
            && data.TryGetProperty("access_pass_id", out var apid)
                ? apid.GetString() : null;

        switch (type)
        {
            case "ag.access_pass.activated":
                await _creds.SetStateByAccessGridIdAsync(accessgridId!, "active", ct); break;
            case "ag.access_pass.suspended":
                await _creds.SetStateByAccessGridIdAsync(accessgridId!, "suspended", ct); break;
            case "ag.access_pass.resumed":
                await _creds.SetStateByAccessGridIdAsync(accessgridId!, "active", ct); break;
            case "ag.access_pass.unlinked":
                await _creds.SetStateByAccessGridIdAsync(accessgridId!, "unlink", ct); break;
            case "ag.access_pass.deleted":
                await _creds.SetStateByAccessGridIdAsync(accessgridId!, "deleted", ct); break;
            // Unknown types fall through — always ack 200.
        }

        await _events.MarkProcessedAsync(id, ct);
        return Ok(new { received = true });
    }
}
```

See [webhook-events.md](./webhook-events.md) for the full event catalog.

## Encryption-at-rest

Use `ValueConverter` plus `IDataProtector` (built-in) or pull from Azure Key Vault / AWS KMS. Apply to `webhooks.bearer_token` and `credential_profile_keys.key_value`:

```csharp
modelBuilder.Entity<Webhook>()
    .Property(w => w.BearerToken)
    .HasConversion(v => _protector.Protect(v), v => _protector.Unprotect(v));
```
