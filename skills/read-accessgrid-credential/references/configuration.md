# Configuration — Keep Keys, AIDs and TCI Out of Firmware

> **If you are a firmware developer, we highly recommend that you allow the TCI, AID and encryption keys be set via some configuration mechanism, perhaps OSDP, simple config files, a config app, or a BLE app.**
>
> This file explains how to deliver and store that configuration so the principle actually holds up in production.

---

## Why

Every value in this list is going to change at some point during the lifetime of a deployed reader:

| Value | Why it changes |
|-------|----------------|
| AES keys (DESFire Simple master / read; Diversified master / privacy) | Disclosure incident, scheduled rotation, customer-specific key sets |
| AccessGrid AIDs | New AID adopted by AG (rare but possible); customer-deployment-specific AIDs |
| Apple ECP2 TCI | Apple updates the wake-up frame; or your customer uses a non-default terminal subtype |
| SmartTap `collector_id` | Reader is RMA'd or repurposed; you re-enroll under a new ID |
| SmartTap long-term EC P-256 private key | Rotation; suspected compromise; RMA |
| Reader address (OSDP) / OSDP secure-channel key | Site config; security policy |
| Logging level, network endpoints, firmware identity | Standard ops |

Any value that "will change" must be configurable. Any value that "will change *under stress*" — incident, customer-driven, large fleet — must be configurable via a channel that doesn't require physical access or a firmware re-flash.

A reader shipped with hard-coded keys is one disclosure away from a fleet-wide truck roll. A reader shipped with config-driven keys can rotate in minutes.

---

## What MUST be configurable

```
ECP / Polling
  - TCI                       (3 bytes, default: 020000)
  - Terminal type / subtype   (defaults: 02 / 02 for Access)
  - TRA flag                  (default: true)

DESFire Simple structure
  - AID                       (big-endian: F56401)
  - Master key  (idx 00)      (AES-128, 16 bytes)
  - Read key    (idx 01)      (AES-128, 16 bytes)

DESFire Key Diversified structure
  - AID                       (big-endian: ACCE55)
  - Master key  (idx 00)      (AES-128, 16 bytes)
  - Privacy key (idx 02)      (AES-128, 16 bytes)
  - Diversified read key      (expression: aes128cmac(privacy, 0102{uid}{aid}…))

Google SmartTap
  - SmartTap AID              (A000000476D0000111)
  - collector_id              (4 bytes, big-endian on the wire)
  - Long-term EC P-256 private key  (PEM, DER, or raw)
  - Long-term key version     (integer)

Reader operations
  - OSDP address              (if OSDP)
  - OSDP secure channel key   (if OSDP)
  - Output mode               (Wiegand bit count, OSDP report format, network endpoint, etc.)
  - Logging level
```

What MAY be hard-coded:

- Protocol *constants* that come from the underlying NXP / Apple / Google specs — DESFire instruction bytes (`5A`, `AA`, `AF`, `BD`), HCE preflight AIDs (`OSE.VAS.01`, `D2760000850100`), JAM-CRC32 polynomial, NDEF type strings. Those are protocol invariants, not deployment knobs.

If you're not sure whether something should be configurable, configurable is the safer default. A config knob you never twist costs nothing. A hard-coded value you need to twist later costs a firmware rollout.

---

## A worked schema (JSON)

Pick JSON, TOML, CBOR, or protobuf to match your platform — the *shape* matters, not the encoding.

```json
{
  "annotation": {
    "type": "ecp.2.access",
    "tci": "020000",
    "tra": true
  },

  "protocols": [
    {
      "type": "desfire",
      "structure": "simple",
      "aid": "F56401",
      "keys": [
        { "id": "master", "type": "aes", "index": 0, "value": "1869e1e47af074f4fcf76a4ba9cf0709" },
        { "id": "read",   "type": "aes", "index": 1, "value": "6e369e1a479c14601d2ed20a4121a67d" }
      ]
    },
    {
      "type": "desfire",
      "structure": "diversified",
      "aid": "ACCE55",
      "keys": [
        { "id": "master",  "type": "aes", "index": 0, "value": "a9f212b7a5c5e04d73af90524a437b39" },
        { "id": "privacy", "type": "aes", "index": 2, "value": "fc26aab3c926c0028ce4c47c8a1b4afb" },
        { "id": "read_derived", "type": "aes", "index": 1,
          "value": "aes128cmac({privacy}, 0102{uid}{aid}aaaaaa)" }
      ]
    },
    {
      "type": "smart_tap",
      "aid": "A000000476D0000111",
      "collector_id": 94223762,
      "keys": {
        "53": "reader-lt-v53.pem"
      }
    }
  ],

  "reader": {
    "output_mode": "osdp",
    "osdp_address": 0,
    "log_level": "info"
  }
}
```

### Notes on the schema

- **Key values** should accept raw hex, base64, *or* a filename pointer (resolved relative to the config file). Hex is convenient for inline AES keys; base64 fits short binary blobs; filenames are right for PEM/DER private keys.
- **Diversified read key** is an *expression*: a templated string that names the source key by id and the variables (`{uid}`, `{aid}`) substituted at runtime. The reader evaluates `aes128cmac(key, data)` to derive the per-card key without ever storing it. See [apple-ecp2-desfire.md](./apple-ecp2-desfire.md) step 4 for the exact AN10922 computation.
- **SmartTap `keys`** is a dict keyed by version, so multiple versions can coexist during rotation. The reader picks the highest-version key when signing, but accepts any if a phone presents an older `key_version`.
- **AIDs** in the config are big-endian (human-readable). Convert to little-endian at the protocol layer, never in the config.

---

## Delivery channels

Pick whatever fits the deployment topology. You can support more than one.

### OSDP

Best fit: door-controller-attached readers on a permanent bus.

- Send config updates as OSDP commands (`osdp_FILETRANSFER`, vendor extensions, or a custom command in the manufacturer-reserved range).
- Use OSDP Secure Channel — never push keys over an unencrypted bus.
- Acknowledge with a CRC over the applied config so the panel can confirm successful update.
- Rotate the OSDP secure-channel key itself via OSDP (yes, you can rotate the bus key over the bus, with care).

### Config file on flash

Best fit: standalone readers, IP readers, embedded Linux platforms.

- JSON / TOML on a known path.
- Verify the file's integrity at boot (Ed25519 signature against an embedded operator pubkey, HMAC against a device-bound secret, etc.).
- Refuse to start if the signature/HMAC fails. Log loudly.

### Config app over USB / serial

Best fit: installation tools, factory provisioning, RMA refresh.

- Authenticated channel — operator credential or hardware token.
- Atomic write: stage the new config, validate, commit, rollback on failure.
- Always log who pushed what version to which serial number.

### BLE provisioning app

Best fit: retrofit installs where pulling cable to a config terminal isn't practical.

- Pair via out-of-band channel (NFC tap, QR scan, button press + PIN) — not promiscuous BLE pairing.
- Encrypted GATT characteristic carries the same config blob as the file or OSDP channel.
- Rate-limit pairing attempts and revoke trust after a configurable number of failures.

### Cloud-pushed config

Best fit: large fleets, SaaS-managed deployments.

- mTLS or signed-payload model.
- Reader pulls on schedule + on demand.
- Idempotent: re-applying the current version is a no-op.
- Versioned: reader reports applied version back to cloud.
- Always retain the ability to fall back to a locally-cached known-good config if the cloud is unreachable.

---

## Key storage on the reader

The least-secure-to-most-secure ladder. Climb as high as your hardware allows.

| Tier | Storage | Notes |
|------|---------|-------|
| 0 (worst) | Plaintext on filesystem / firmware image | **Do not ship.** |
| 1 | Encrypted with a key derived from a device-bound secret (CPU UID, eFuse) | Better than plain but not great — UID is readable to anyone with the chip. |
| 2 | Encrypted flash partition (LUKS, dm-crypt, vendor secure boot) | Acceptable for IP / Linux readers. |
| 3 | TPM / TEE-sealed | Good. Keys never leave the secure element in plaintext. |
| 4 | Discrete secure element (ATECC608, SE050, OPTIGA TPM) | Best. Use the SE's ECDH primitive directly for SmartTap. |

For the SmartTap **long-term EC private key** specifically, tier 3 or 4 is strongly recommended. If your SE supports ECDH on P-256 (almost all do), you never need to materialize the private key in firmware memory — the ECDH operation happens inside the SE. The reader handles only the ephemeral keypair (which it generates fresh per tap) and the derived session keys.

For the **AES keys**, tier 3 or 4 is strongly recommended.

---

## Key rotation

A reader that can't rotate keys is a reader you'll regret.

### Multi-version support

Configure the reader to accept multiple versions of each key during overlap windows:

```json
"keys": [
  { "id": "read", "index": 1, "value": "<new key>",     "version": 2, "since": "2026-06-01T00:00:00Z" },
  { "id": "read", "index": 1, "value": "<current key>", "version": 1, "until": "2026-06-30T23:59:59Z" }
]
```

During the overlap, the reader tries the higher-version key first; if auth fails with `91 AE`, falls back to the older key. After the cutoff, the older key is removed in the next config push.

A reader that supports multiple keys per index — iterating until one authenticates successfully — handles rotation transparently. The pseudo-code in [reference-implementation.md](./reference-implementation.md) shows the pattern.

### Audit

Log every config apply event with:

- New config version / hash.
- Who / what pushed it (operator ID, system ID).
- Which fields changed (without logging the *values* of secret fields).
- Result (applied / rejected with reason).

For AES keys and the LT private key, log only the **key version** when authenticating, never the value. A log line that includes `"used_key_version": 2` is normal; a log line that includes the AES key in hex is a vulnerability.

### Revocation

If a reader is RMA'd, lost, or repurposed:

1. Mark its `collector_id` revoked in your AG console (SmartTap side).
2. Push a config that overwrites all keys to dummy values, or wipe the secure partition.
3. Confirm the reader can no longer decrypt traffic before sending it for refurbishment.

---

## Logging and PII

Decrypted credential payloads are PII. So are SmartTap `customer_id` and `tap_id`.

- Never log decrypted payloads at INFO. DEBUG only, and even then redact when shipping to a centralized log store.
- Hash `customer_id` if you need to count uniques without storing identifiers.
- Rotate logs and apply retention policies that match your privacy framework (GDPR, CCPA, customer-specific).

---

## Bootstrap problem

How does a brand-new reader get its *first* config?

Patterns that work:

- **Factory-provisioned default config** — a config blob signed by an operator key, embedded in the firmware image, that contains a bootstrap public key and the location of the real config service. Reader fetches and validates the real config at first boot, then discards the bootstrap.
- **Installation tool** — physical pairing (USB / serial / NFC tap) by a trusted installer who pushes the initial config.
- **QR-tap-to-pair** — installer's mobile app shows a QR; reader scans it via its NFC frontend; QR carries a one-time bootstrap secret.

Whichever you pick: the bootstrap config itself does **not** contain production AG keys. It only contains enough to pull the real config from your delivery channel.

---

## TL;DR — the rule

**No AccessGrid AES key, no AID, no TCI, no SmartTap collector ID, no long-term EC private key is allowed in the firmware binary.** Everything load-bearing comes from runtime configuration delivered via a channel that lets you rotate without re-flashing.

A firmware update should be needed only when the *code* changes — never just to swap a key.
