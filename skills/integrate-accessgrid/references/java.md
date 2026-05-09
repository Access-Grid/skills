# Java Patterns

Use this file when the host stack is Java.

## Official SDK Shape

The README shows:

- `new AccessGrid(accountId, secretKey)`
- `client.accessCards()` for access-card lifecycle work
- `client.console()` for enterprise console features

```java
AccessGrid client = new AccessGrid(
    System.getenv("ACCOUNT_ID"),
    System.getenv("SECRET_KEY")
);
```

The SDK should own `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Access Pass Provisioning

```java
Map<String, Object> payload = new HashMap<>();
payload.put("card_template_id", "0xd3adb00b5");
payload.put("employee_id", "123456789");
payload.put("site_code", credential.siteCode());
payload.put("card_number", credential.cardNumber());
payload.put("full_name", credential.fullName());
payload.put("email", credential.email());
payload.put("phone_number", credential.phoneNumber());
payload.put("classification", credential.classification());
payload.put("metadata", Map.of("pacs_credential_id", credential.id()));

Card card = client.accessCards().provision(payload);
```

## Lifecycle Operations

The Java README excerpt I verified did not show suspend/resume/delete examples. Confirm those exact method names in the package source or live docs before using them.

## Console Resources

```java
Map<String, Object> template = client.console().createTemplate(
    Map.of(
        "name", "Employee Access Pass",
        "platform", "apple",
        "use_case", "corporate_id",
        "protocol", "desfire"
    )
);
```

## Webhook Handling

The Java README excerpt I verified did not show receiver verification code. Build that from the official webhook docs.

```java
@RestController
public final class AccessGridWebhookController {
    @PostMapping("/webhooks/accessgrid")
    public ResponseEntity<Map<String, Object>> handle(
        @RequestBody String rawBody
    ) throws Exception {
        WebhookEvent event = objectMapper.readValue(rawBody, WebhookEvent.class);
        if (webhookEventsRepo.hasProcessed(event.id())) {
            return ResponseEntity.ok(Map.of("ok", true, "duplicate", true));
        }

        webhookEventsRepo.markReceived(event.id(), event.type());

        switch (event.type()) {
            case "credential.suspended" ->
                credentialsRepo.markSuspendedByAccessGrid(event.data().metadata().pacsCredentialId());
            case "credential.resumed" ->
                credentialsRepo.markActiveByAccessGrid(event.data().metadata().pacsCredentialId());
            default -> webhookEventsRepo.markIgnored(event.id());
        }

        webhookEventsRepo.markProcessed(event.id());
        return ResponseEntity.ok(Map.of("ok", true));
    }
}
```
