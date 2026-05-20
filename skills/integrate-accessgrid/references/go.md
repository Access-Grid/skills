# Go Patterns

Use this file when the host stack is Go.

## Install

```bash
go get github.com/Access-Grid/accessgrid-go
```

```go
import accessgrid "github.com/Access-Grid/accessgrid-go"
```

Requires Go 1.18+.

## Client

```go
client, err := accessgrid.NewClient(
    os.Getenv("ACCOUNT_ID"),
    os.Getenv("SECRET_KEY"),
)
if err != nil {
    log.Fatalf("accessgrid: %v", err)
}
```

The SDK owns `X-ACCT-ID` / `X-PAYLOAD-SIG` signing. Keep any raw HTTP fallback in one adapter.

## Provisioning

```go
card, err := client.AccessCards.Provision(ctx, accessgrid.ProvisionParams{
    CardTemplateID: template.AccessGridID,
    EmployeeID:     credential.Holder.ExternalID,
    FullName:       credential.Holder.FullName,
    Email:          credential.Holder.Email,
    Metadata: map[string]string{
        "pacs_credential_id": credential.ID,
    },
})
if err != nil {
    return fmt.Errorf("provision: %w", err)
}

// Persist before returning.
if err := credentials.AttachAccessGridID(ctx, credential.ID, card.ID); err != nil {
    // Compensate: if we can't persist, the AG record is orphaned.
    // Best-effort delete on AG side, then bubble the error.
    _ = client.AccessCards.Delete(ctx, card.ID)
    return err
}
```

## Lifecycle

```go
err := client.AccessCards.Suspend(ctx, accessgridID)
err  = client.AccessCards.Resume(ctx, accessgridID)
err  = client.AccessCards.Unlink(ctx, accessgridID)
err  = client.AccessCards.Delete(ctx, accessgridID)
```

Confirm method names against the installed module version.

## Webhook receiver

```go
func HandleAccessGridWebhook(w http.ResponseWriter, r *http.Request) {
    if r.Header.Get("Authorization") != "Bearer "+os.Getenv("ACCESSGRID_WEBHOOK_BEARER") {
        http.Error(w, "unauthorized", http.StatusUnauthorized)
        return
    }

    body, err := io.ReadAll(r.Body)
    if err != nil { http.Error(w, "bad body", http.StatusBadRequest); return }

    var event struct {
        SpecVersion string          `json:"specversion"`
        ID          string          `json:"id"`
        Source      string          `json:"source"`
        Type        string          `json:"type"`
        Data        json.RawMessage `json:"data"`
    }
    if err := json.Unmarshal(body, &event); err != nil {
        http.Error(w, "bad json", http.StatusBadRequest); return
    }
    if event.SpecVersion != "1.0" || event.Source != "accessgrid" {
        http.Error(w, "bad envelope", http.StatusBadRequest); return
    }

    seen, _ := webhookEventsRepo.HasProcessed(r.Context(), event.ID)
    if !seen {
        _ = webhookEventsRepo.MarkReceived(r.Context(), event.ID, event.Type)

        var data struct {
            AccessPassID string `json:"access_pass_id"`
        }
        _ = json.Unmarshal(event.Data, &data)

        switch event.Type {
        case "ag.access_pass.activated":
            _ = credentialsRepo.SetStateByAccessGridID(r.Context(), data.AccessPassID, "active")
        case "ag.access_pass.suspended":
            _ = credentialsRepo.SetStateByAccessGridID(r.Context(), data.AccessPassID, "suspended")
        case "ag.access_pass.resumed":
            _ = credentialsRepo.SetStateByAccessGridID(r.Context(), data.AccessPassID, "active")
        case "ag.access_pass.unlinked":
            _ = credentialsRepo.SetStateByAccessGridID(r.Context(), data.AccessPassID, "unlink")
        case "ag.access_pass.deleted":
            _ = credentialsRepo.SetStateByAccessGridID(r.Context(), data.AccessPassID, "deleted")
        // Unknown types fall through — still ack 200.
        }

        _ = webhookEventsRepo.MarkProcessed(r.Context(), event.ID)
    }

    w.Header().Set("Content-Type", "application/json")
    _ = json.NewEncoder(w).Encode(map[string]bool{"received": true})
}
```

See [webhook-events.md](./webhook-events.md) for the full event catalog.

## Encryption-at-rest

Implement GORM `Scanner`/`Valuer` (or equivalent in your ORM) that wraps AES-GCM with a key fetched from KMS / Vault. Apply to `webhooks.bearer_token` and `credential_profile_keys.key_value`.
