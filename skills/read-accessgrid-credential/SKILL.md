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
| 2 | Decide scope and feedback | Transports + reader-local feedback (sound / LED) + device-side error reporting locked |
| 3 | Set up configuration plumbing | Config delivery mechanism wired *before* keys touch firmware |
| 4 | Implement Apple ECP2 / DESFire | Both Simple and Key Diversified structures |
| 5 | Implement Google SmartTap | Reader enrolled with AG, ECDH + decryption working |
| 6 | Integrate with the access-control bus | OSDP / Wiegand / network output, plus feedback routing |
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

## Phase 2 — Decide scope and feedback

Three sub-decisions. Ask each **separately** and record all three in the config schema (Phase 3) — they're load-bearing for hardware (Phase 1 if not already locked), config (Phase 3), protocol implementation (Phases 4–5), and host-bus wiring (Phase 6).

### Step 2a — Transport scope

Ask: "Which wallet transports should this reader support?"

- **Both transports (recommended).** The right answer for any production reader. Apple Wallet and Google Wallet devices will both tap it.
- **Apple only.** Defensible if your install base is exclusively Apple Wallet (closed enterprise rollout where you control device choice).
- **Google only.** Rare; usually only happens during phased rollouts.

If you start with one, scaffold the config and dispatch logic for the other from day one — see [references/configuration.md](./references/configuration.md).

### Step 2b — Reader-local feedback (sound, LEDs)

Ask: "How should the reader give feedback to the user at the moment of the tap — sound, LEDs, both, or none (host-driven only)?"

| Option | What it implies for hardware + firmware |
|--------|------------------------------------------|
| **Buzzer / beeper only** | Piezo or driven speaker on the reader. Firmware emits tones at each outcome (success / failure / activity). No visual feedback. |
| **LEDs only** | One or more LEDs (typically a single RGB or a green + red pair). Firmware drives them at each outcome. Choose this when the install environment is noise-sensitive (hospitals, libraries). |
| **Both (recommended)** | Industry default. A short beep + green flash on success, a longer buzz + red flash on failure. Most accessible — covers users who can't hear and users who can't see the indicator. |
| **None — host-driven only** | The reader emits the card-data report; the panel / controller drives any LEDs or sounders via OSDP / Wiegand-and-side-channel commands. Pick this when the panel already owns the UX and you don't want two systems disagreeing. |

Follow-ups to ask once the option is chosen:

1. **Outcomes to differentiate.** Minimum two (success / failure). Common richer sets: idle / activity-on-tap / success-granted / failure-denied / config-error / offline. Ask which outcomes need a distinct cue.
2. **Source of truth.** Does the reader decide success/failure (it has read the credential successfully → beep + green), or does the host's grant/deny decision drive the feedback (reader reads, sends to panel, panel sends back a beep/LED command)? OSDP supports both; pick one and document it. Mixing them causes double-beeps and conflicting LED states.
3. **Hardware presence.** Confirm the chosen NFC frontend / reader board actually has the LEDs and buzzer the answer assumes. If not, Phase 1 needs to revisit.

Record the answer in the config schema as `feedback.mode` (`buzzer` / `led` / `both` / `host`) plus the per-outcome cue table. See [references/configuration.md](./references/configuration.md).

### Step 2c — Device-side error responses (phone / watch)

Ask: "On a failed read — wrong key, malformed payload, auth failure, decompression error, etc. — do you want the reader to return an explicit error response to the phone / watch so the wallet can show feedback to the user, or stay silent (drop the field)?"

| Option | What it means in protocol terms |
|--------|----------------------------------|
| **Return errors (recommended for consumer-facing deployments)** | DESFire: respond with the real EV1 status word (`91 AE` auth fail, `91 9D` permission denied, `91 1C` illegal command, `91 7E` length error, etc.) so Apple Wallet can show a "Try again" prompt instead of timing out. SmartTap: respond with the appropriate error status (e.g. `6982` security status not satisfied, `6A88` referenced data not found) so Google Wallet's UI can react. |
| **Stay silent — drop the field** | Reader simply stops responding; phone times out. Useful for high-throughput access points where a slow error UI on the device would block the queue, or when you specifically don't want to leak which step failed to a hostile prober. |
| **Generic-only errors** | Compromise: return a single generic failure status (e.g. `6F00` / `91 1E`) for *all* failure modes so the device can prompt the user to retry, without disclosing whether the failure was key auth, integrity, or otherwise. Recommended when phishing / probing is a concern. |

Follow-ups to ask:

1. **Granularity.** If returning errors, do you want **specific** status words per failure mode (better UX, leaks information) or **generic** (worse UX, opaque to a prober)? Pick one policy and apply it consistently — never specific on auth and generic on integrity.
2. **Watch behavior.** Apple Watch in particular can present pass-specific prompts on certain status codes. If the deployment includes Apple Watch users, lean toward returning errors so the watch can re-prompt the wearer instead of looking dead.
3. **Logging.** Whichever choice, the reader still logs the *real* failure reason locally with the tag UID — the device-facing response is independent of the internal log line.

Record the answer in the config schema as `feedback.device_errors` (`specific` / `generic` / `silent`).

### Lock the choices

Write Step 2a / 2b / 2c outcomes into the config schema before continuing to Phase 3. The decisions drive hardware confirmation, config schema, the return-code-to-cue mapping in Phase 4 / 5, and the host-bus wiring in Phase 6.

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

### Routing the feedback signals from Phase 2b

The decision in Phase 2b (sound / LED / both / host-driven) decides who owns the cue.

- **Reader-driven** — firmware fires the buzzer and LEDs from the read-loop's outcome (`AG_OK` / `AG_ERR_*`). Fast, no round-trip. Useful when the panel's grant/deny decision matches "did the read succeed" closely enough (Wiegand readers usually run this way).
- **Host-driven** — reader emits the card-data report and waits; the panel sends explicit feedback commands. OSDP carries this natively:
  - `osdp_LED` — color, on/off duration, temporary vs. permanent.
  - `osdp_BUZ` — beeper count, on-time, off-time, repeat.
  - `osdp_TEXT` — for readers with a small display.
- **Both** — common pattern: reader fires a short "I read something" cue locally (e.g. one quick beep, amber blink), then the panel's `osdp_LED` / `osdp_BUZ` overrides with the final grant/deny indication. Document the precedence rule.

Whichever you wired in Phase 2b, route the relevant config (`feedback.mode`, the per-outcome cue table) into your bus-output module. Don't reach for new globals — use the same `cfg` object.

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
- [ ] Reader-local feedback matches Phase 2b: a success tap produces the configured success cue (sound and/or LED); a failure produces the configured failure cue. Cues are distinguishable in a noisy environment for the deployment.
- [ ] Host-driven feedback path (if enabled) — `osdp_LED` / `osdp_BUZ` from the panel reaches the reader and overrides / supplements the local cue per the documented precedence.
- [ ] Device-side error responses match Phase 2c: induce wrong-key, integrity-fail, and malformed-payload conditions; confirm Apple Wallet and Google Wallet show the expected behavior (retry prompt, generic failure, or silent timeout) on real devices including Apple Watch if in scope.
- [ ] No information leak in error responses if the policy is "generic" — verify the same status word is returned for distinct failure modes.

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
- Mixing the device-error policy across failure modes — being "specific" on auth failures but "generic" on integrity failures lets a prober distinguish them. Pick one policy in Phase 2c and apply it consistently.
- Driving the buzzer and LEDs from **both** the reader and the panel without a documented precedence rule — you'll ship double-beeps and conflicting LED states.
