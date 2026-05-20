# Java Patterns

Use this file when the host stack is Java.

## Install

**Maven:**
```xml
<dependency>
    <groupId>com.accessgrid</groupId>
    <artifactId>access-grid-sdk</artifactId>
    <version>1.3.0</version>
</dependency>
```

**Gradle:**
```groovy
implementation 'com.accessgrid:access-grid-sdk:1.3.0'
```

Requires Java 11+. Bump the version to the latest release when starting a new integration — check https://github.com/Access-Grid/accessgrid-java/releases.

## Client

```java
AccessGridClient client = new AccessGridClient(
    System.getenv("ACCOUNT_ID"),
    System.getenv("SECRET_KEY")
);
```

The SDK owns `X-ACCT-ID` and `X-PAYLOAD-SIG` signing.

## Provisioning

```java
ProvisionCardRequest request = ProvisionCardRequest.builder()
    .cardTemplateId(template.getAccessgridId())
    .employeeId(credential.getHolder().getExternalId())
    .tagId(credential.getCardNumber())
    .fullName(credential.getHolder().getFullName())
    .email(credential.getHolder().getEmail())
    .metadata(Map.of("pacs_credential_id", credential.getId().toString()))
    .build();

Card card = client.accessCards().provision(request);

credentialsRepo.attachAccessGridId(credential.getId(), card.getId());
```

## Lifecycle

```java
client.accessCards().suspend(accessgridId);
client.accessCards().resume(accessgridId);
client.accessCards().unlink(accessgridId);
client.accessCards().delete(accessgridId);
```

Confirm method names against the installed SDK version.

## Webhook receiver (Spring)

```java
@RestController
public final class AccessGridWebhookController {

    @Value("${accessgrid.webhook.bearer}")
    private String expectedBearer;

    @PostMapping(value = "/webhooks/accessgrid",
                 consumes = "application/cloudevents+json")
    public ResponseEntity<Map<String, Boolean>> handle(
            @RequestHeader(value = "Authorization", required = false) String auth,
            @RequestBody Map<String, Object> event) {

        if (auth == null || !auth.equals("Bearer " + expectedBearer)) {
            return ResponseEntity.status(401).build();
        }
        if (!"1.0".equals(event.get("specversion")) ||
            !"accessgrid".equals(event.get("source"))) {
            return ResponseEntity.badRequest().build();
        }

        String eventId = (String) event.get("id");
        if (webhookEventsRepo.hasProcessed(eventId)) {
            return ResponseEntity.ok(Map.of("received", true));
        }
        webhookEventsRepo.markReceived(eventId, (String) event.get("type"));

        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) event.getOrDefault("data", Map.of());
        String accessgridId = (String) data.get("access_pass_id");

        switch ((String) event.get("type")) {
            case "ag.access_pass.activated" ->
                credentialsRepo.setStateByAccessGridId(accessgridId, "active");
            case "ag.access_pass.suspended" ->
                credentialsRepo.setStateByAccessGridId(accessgridId, "suspended");
            case "ag.access_pass.resumed" ->
                credentialsRepo.setStateByAccessGridId(accessgridId, "active");
            case "ag.access_pass.unlinked" ->
                credentialsRepo.setStateByAccessGridId(accessgridId, "unlink");
            case "ag.access_pass.deleted" ->
                credentialsRepo.setStateByAccessGridId(accessgridId, "deleted");
            default -> { /* Unknown — log and ack */ }
        }

        webhookEventsRepo.markProcessed(eventId);
        return ResponseEntity.ok(Map.of("received", true));
    }
}
```

See [webhook-events.md](./webhook-events.md) for the full event catalog.

## Encryption-at-rest

Implement a JPA `AttributeConverter` that wraps AES-GCM with a key from your KMS (AWS Secrets Manager, Vault, Azure Key Vault). Apply to `webhooks.bearer_token` and `credential_profile_keys.key_value`:

```java
@Converter
public class EncryptedStringConverter implements AttributeConverter<String, String> {
    public String convertToDatabaseColumn(String plain)   { return kms.encrypt(plain); }
    public String convertToEntityAttribute(String cipher) { return kms.decrypt(cipher); }
}

@Entity
class Webhook {
    @Convert(converter = EncryptedStringConverter.class)
    private String bearerToken;
}
```
