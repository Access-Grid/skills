---
name: read-accessgrid-credential
description: Implement reader firmware that consumes AccessGrid mobile wallet credentials over NFC (Apple Wallet ECP2/DESFire and Google Wallet SmartTap). Use when building reader hardware or firmware — bare-metal MCU, embedded Linux, or similar — that needs to verify and read AccessGrid-issued mobile passes.
---

# Read AccessGrid Credential

For firmware and hardware teams building a reader that accepts AccessGrid mobile wallet credentials. The goal is a reader that wakes up the wallet, completes the cryptographic handshake, reads the credential payload, and hands the parsed data to your access-control pipeline.

There are **two credential transports** AccessGrid issues today; a complete reader implements both:

| Transport | Used by | Underlying protocol |
|-----------|---------|----------------------|
| **Apple ECP2 / DESFire** | Apple Wallet devices | NFC Enhanced Contactless Polling v2 → ISO 14443A-4 → DESFire EV1 native commands |
| **Google SmartTap** | Google Wallet devices | ISO 7816 SELECT → SmartTap 2.0 ECDH key agreement → encrypted record bundle |

See [references/apple-ecp2-desfire.md](./references/apple-ecp2-desfire.md) and [references/google-smarttap.md](./references/google-smarttap.md) for the protocol-level deep dives.

---

> ## ⚠️ The Config-Driven Principle
>
> **If you are a firmware developer, we highly recommend that you allow the TCI, AID and encryption keys be set via some configuration mechanism — perhaps OSDP, simple config files, a config app, or a BLE app.**
>
> Do not hard-code TCI bytes, AIDs, AES keys, the SmartTap collector ID, or the long-term EC private key into the firmware image. They will need to rotate. Customers will deploy in environments you didn't anticipate. The cost of "we shipped 50,000 readers with a baked-in key" is measured in months or years of remediation. See [references/configuration.md](./references/configuration.md) for delivery patterns.

---

## What you're building

A reader loop that, for every tap, does roughly this:

1. **Wake / poll** with an ECP2 annotation frame (Apple) or a standard ISO 14443 / 7816 select sequence (Android).
2. **Select** the AccessGrid application — by AID on DESFire, by DF name on SmartTap.
3. **Authenticate** — DESFire EV1 three-pass AES for Apple, ECDH + HKDF for Google.
4. **Read** the encrypted payload.
5. **Verify** integrity (CRC for DESFire, HMAC for SmartTap).
6. **Emit** to your system (OSDP, Wiegand, REST, MQTT, whatever the host expects).

The two transport-specific reference files walk through every step.

## Orientation phases

| # | Phase | Output |
|---|-------|--------|
| 1 | Hardware and platform | NFC frontend chosen; OS / runtime decided |
| 2 | Decide scope | Apple only, Google only, or both (almost always both) |
| 3 | Set up configuration plumbing | Config delivery mechanism wired *before* keys touch firmware |
| 4 | Implement Apple ECP2 / DESFire | Both Simple and Key Diversified structures |
| 5 | Implement Google SmartTap | Reader enrolled with AG, ECDH + decryption working |
| 6 | Integrate with the access-control bus | OSDP / Wiegand / network output |
| 7 | Field testing | Real Apple Wallet devices, real Google Wallet devices, real failure modes |

Phase 3 is non-negotiable. Wire your config plumbing first, then load real keys into it. Never the other way around.

---

## Phase 1 — Hardware and platform

The skill is hardware-agnostic but the choice constrains everything downstream.

Common NFC frontends used for AccessGrid readers:

- **NXP PN5180 / PN7160** — recommended for new builds; supports ECP2 polling frames and DESFire EV1 native commands natively.
- **NXP PN532 / MFRC522** — older parts; can work but ECP2 frame construction and DESFire crypto sit on you.
- **PC/SC + USB readers** (e.g., ACS ACR1252, CIRCONTROLS) — the simplest path for prototyping; both reference implementations use this class of reader.
- **Embedded modules** (Springcard, ELATEC, IDTECH) — vendor SDKs vary; check whether they expose ECP2 frame transmission and DESFire native-command pass-through.

Two things the frontend MUST support:

1. **Transparent / low-level mode** — you need to send raw ECP2 polling frames (`6A 02 …`) for Apple Wallet wake-up. Higher-level "read NDEF" abstractions won't expose this.
2. **DESFire EV1 native pass-through** — Apple Wallet HCE surfaces as a DESFire applet over ISO 14443A-4. You need to send INS bytes `5A`, `AA`, `AF`, `BD` and parse the `91 xx` status words. Some reader vendors hide this behind a higher-level "MIFARE" API.

Platform / runtime: bare-metal MCU, embedded Linux, or RTOS. The cryptography (AES-128 CBC, AES-128 CMAC, ECDH P-256, HKDF-SHA256, HMAC-SHA256, AES-CTR) is the same across all of them. Pull in a vetted embedded crypto library — mbedTLS, wolfSSL, or your silicon vendor's hardware-accelerated crypto API. Never roll your own primitives.

---

## Phase 2 — Decide scope

- **Both transports.** The right answer for any production reader. Apple Wallet and Google Wallet devices will both tap it.
- **Apple only.** Defensible if your install base is exclusively Apple Wallet (closed enterprise rollout where you control device choice).
- **Google only.** Rare; usually only happens during phased rollouts.

If you start with one, scaffold the config and dispatch logic for the other from day one — see [references/configuration.md](./references/configuration.md).

---

## Phase 3 — Set up configuration plumbing

**Build this before you write a single line of crypto.**

The minimum config surface, per reader unit:

```
- ECP2 annotation frame
  - TCI (3 bytes, e.g. 020000)
- DESFire protocol
  - AID(s) — Simple (F56401) and/or Key Diversified (ACCE55)
  - Keys — index, type (AES-128), value (16 bytes), and any derivation expression
- SmartTap protocol
  - collector_id (4 bytes)
  - long-term EC P-256 private key (PEM, DER, or raw — your choice)
  - key version
- Reader identity / logging / OSDP address / etc.
```

Delivery channels — pick whichever fit the deployment:

- **OSDP** — for door-controller-attached readers, the bus your reader is already on. Carries config updates as OSDP commands.
- **Config file** — JSON/TOML on flash, loaded at boot. See [references/configuration.md](./references/configuration.md) for a worked schema.
- **Config app** — desktop or mobile app that writes config over USB/serial.
- **BLE provisioning app** — installer pairs and pushes config; common for retrofit deployments.
- **Cloud-pushed** — signed payload over mTLS or pre-shared key, useful for fleets.

Whatever you pick, the rule is: **the firmware binary contains no AccessGrid keys, no TCI, no AIDs, no collector ID, no LT private key.** It only contains the *code* to consume them from config.

See [references/configuration.md](./references/configuration.md) for schema, key storage, rotation, and audit guidance.

---

## Phase 4 — Implement Apple ECP2 / DESFire

Read [references/apple-ecp2-desfire.md](./references/apple-ecp2-desfire.md) end-to-end. The transport breaks into:

- **ECP2 polling frame** with TCI `020000` — wakes up Apple Wallet on the phone and tells it to present an access pass.
- **ISO 7816 preflight** (HCE-specific) — SELECT BY NAME `OSE.VAS.01` and `D2760000850100` so Apple Wallet exposes the underlying DESFire applet.
- **DESFire SELECT APPLICATION** — Simple structure AID `F56401` or Key Diversified AID `ACCE55`.
- **DESFire EV1 AES three-pass authentication** — INS `AA` / `AF` with the read key (or the derived key for Key Diversified).
- **For Key Diversified only**: authenticate with the Privacy key, read the real UID, then compute the per-card read key via AES-128 CMAC per AN10922.
- **ReadData** (INS `BD`) on file 00, in CommMode=Fully Encrypted.
- **Session-key crypto**: derive session key from RndA/RndB halves; running IV via CMAC; AES-CBC decrypt; ISO 9797-1 method 2 unpad; JAM-CRC32 verify.
- **Payload parse**: 32-byte file → bit count + card data (Wiegand 26 / 34 / custom).

The full keys, AIDs, and walkthrough are in the reference. **Read it from a config**, not from the literal hex in the reference file.

---

## Phase 5 — Implement Google SmartTap

Read [references/google-smarttap.md](./references/google-smarttap.md). The transport breaks into:

- **Reader enrollment with AccessGrid** — get your `collector_id` (4-byte integer) and register your reader's long-term EC P-256 public key. You hold the private key.
- **Standard ISO 14443A-4 activation** — no ECP2 frame; the phone is in HCE for SmartTap.
- **ISO 7816 SELECT BY DF NAME** for the SmartTap 2.0 AID.
- **Negotiate Secure Channel** — reader generates an ephemeral EC P-256 key and a 32-byte nonce, signs `(reader_nonce || device_nonce || collector_id || reader_ephemeral_pub)` with the long-term key.
- **ECDH** between the reader ephemeral private key and the phone ephemeral public key.
- **HKDF-SHA256** to derive 48 bytes → 16-byte AES key + 32-byte HMAC key.
- **GET DATA** — encrypted, possibly compressed, record bundle.
- **AES-CTR decrypt** + **HMAC-SHA256 verify** + optional **zlib decompress**.
- **NDEF parse** → Customer / Pass objects with issuer ID, customer ID, tap ID.

The keys you hold here (the LT private key, the collector_id) are reader-specific, not AccessGrid-wide. Treat them like a TLS server cert: rotate-able, revocable, never in source.

---

## Phase 6 — Integrate with the access-control bus

Once the credential is read and parsed, hand it to whatever your reader's host expects:

- **OSDP** — the dominant modern bus. Cardholder data goes as a Card Data Report (osdp_RAW or osdp_FMT).
- **Wiegand** — legacy but still everywhere. Drive D0/D1 with the parsed bit stream.
- **Network output** — REST POST, MQTT publish, gRPC — for IP readers.

This is fully host-specific and out of scope for the protocol references. Match the existing access-control conventions.

---

## Phase 7 — Field testing

Minimum acceptable verification before shipping:

- [ ] Read an Apple Wallet access pass from at least three Apple Wallet device generations (cover both phone and watch form factors).
- [ ] Read a Google Wallet access pass from at least three Android handsets across two vendors.
- [ ] Read both Simple and Key Diversified DESFire structures (provision sample passes in both flavors during AG account setup).
- [ ] Read while phone is in low-power mode / locked / on the charger.
- [ ] Failure cases that should not crash the reader: cancelled tap mid-handshake, wrong-key auth failure, phone moves out of field during ReadData, malformed payload.
- [ ] Concurrent taps from two devices in the field (some readers can poll multiple targets).
- [ ] Key rotation works — push a new key via your config channel without flashing firmware.
- [ ] Reader recovers from an unplugged-then-replugged NFC frontend.

---

## Reference implementation

A language-neutral pseudo-code walkthrough of both transports — top-level loop, dispatch, full Apple ECP2/DESFire flow (Simple and Key Diversified), full Google SmartTap flow, plus a verification checklist — lives in [references/reference-implementation.md](./references/reference-implementation.md).

It's pseudo-code, not a port target. Read it to confirm you understand the wire format and the control flow, then implement against your actual NFC frontend's SDK and your chosen crypto library. The pseudo-code names cryptographic primitives (e.g. `aes128_cmac`, `ecdh_p256`, `hmac_sha256`) as function calls — do **not** implement those yourself; use vetted libraries.

---

> ## ⚠️ Reminder: The Config-Driven Principle
>
> **TCI, AIDs, AES keys, the SmartTap collector ID, and the long-term EC private key — all of them — must be loadable at runtime via OSDP, a config file, a config app, or BLE provisioning. None of them belong in the firmware binary.**
>
> This is the difference between a reader you can ship to 50,000 doors and confidently rotate keys on, and a reader that becomes a fleet-wide remediation when a key leaks.

---

## What to avoid

- Hard-coding TCI, AIDs, or keys into the firmware image.
- Shipping a reader without a key-rotation path.
- Skipping the Apple Wallet HCE preflight (`OSE.VAS.01` / `D2760000850100`) — Apple Wallet won't expose the DESFire applet without it.
- Using the wrong-direction byte order on AIDs (`F56401` vs `0164F5`) — the wire format is little-endian; most config files use the big-endian human-readable form. Convert once at config-load, never in the protocol layer.
- Implementing only the Simple DESFire structure when the customer wanted Key Diversified — verify which structure the issued passes use.
- Rolling your own AES or HMAC implementation. Use vetted libraries.
- Logging decrypted credential payloads to disk at INFO. They are PII.
- Trusting status words alone — verify the CRC (DESFire) and HMAC (SmartTap) on every read.
- Caching the LT EC private key in plaintext on the filesystem. Use a TPM, SE, or HSM if available; otherwise an encrypted flash partition with a key bound to device identity.
