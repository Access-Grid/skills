# Go Patterns

Use this file when the host stack is Go.

## Official SDK Shape

The README shows:

- `accessgrid.NewClient(accountID, secretKey)`
- `client.AccessCards` for access-card lifecycle work
- `client.Console` for enterprise console features

```go
client := accessgrid.NewClient(
	os.Getenv("ACCESSGRID_ACCOUNT_ID"),
	os.Getenv("ACCESSGRID_SECRET_KEY"),
)
```

The SDK should own `X-ACCT-ID` and `X-PAYLOAD-SIG` signing. Keep any raw HTTP fallback in one adapter.

## Access Pass Provisioning

The README shows provisioning with typed parameters rather than a freeform map:

```go
card, err := client.AccessCards.Provision(ctx, accessgrid.AccessCardProvisionParams{
	CardTemplateID: "0xd3adb00b5",
	EmployeeID:     "123456789",
	SiteCode:       credential.SiteCode,
	CardNumber:     credential.CardNumber,
	FullName:       credential.FullName,
	Email:          credential.Email,
	PhoneNumber:    credential.PhoneNumber,
	Classification: credential.Classification,
	Metadata: map[string]string{
		"pacs_credential_id": credential.ID,
	},
})
```

Wrap it in a host service so dedupe, logging, and persistence stay local to the host app.

## Lifecycle Operations

The README excerpt I verified did not show suspend/resume/delete examples for Go. Use the official docs or package source for exact method names before writing those calls.

## Console Resources

The README explicitly shows console helpers such as template creation and webhook creation:

```go
template, err := client.Console.CreateTemplate(ctx, accessgrid.CardTemplateParams{
	Name:     "Employee Access Pass",
	Platform: "apple",
	UseCase:  "corporate_id",
	Protocol: "desfire",
})

webhook, err := client.Console.CreateWebhook(ctx, accessgrid.WebhookParams{
	Name:      "Prod Webhook",
	TargetURL: "https://host.example.com/webhooks/accessgrid",
})
```

## Webhook Handling

The Go README excerpt I verified shows webhook creation, not receiver verification. Build inbound handling from the official webhook docs and the webhook object returned by the API.

```go
func HandleAccessGridWebhook(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}

	var event WebhookEvent
	if err := json.Unmarshal(body, &event); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}

	if webhookEventsRepo.HasProcessed(r.Context(), event.ID) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "duplicate": true})
		return
	}

	_ = webhookEventsRepo.MarkReceived(r.Context(), event.ID, event.Type)
	switch event.Type {
	case "credential.suspended":
		_ = credentialsRepo.MarkSuspendedByAccessGrid(r.Context(), event.Data.Metadata.PACSCredentialID)
	case "credential.resumed":
		_ = credentialsRepo.MarkActiveByAccessGrid(r.Context(), event.Data.Metadata.PACSCredentialID)
	default:
		_ = webhookEventsRepo.MarkIgnored(r.Context(), event.ID)
	}
	_ = webhookEventsRepo.MarkProcessed(r.Context(), event.ID)
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}
```
