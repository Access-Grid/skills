# Apple ECP2 / DESFire Reader Implementation

Apple Wallet exposes AccessGrid credentials over a DESFire EV1 applet, wrapped in Apple's Enhanced Contactless Polling v2 (ECP2). This file is the complete protocol reference. Every hex value comes from https://www.accessgrid.com/guides/knowledgebase/accessgrid-desfire-application-structures.

> **Config-driven reminder.** Every byte sequence below — TCI, AIDs, AES keys — is shown so you understand the protocol. **None of them should be hard-coded in your firmware.** Load all of them from your config plumbing (see [configuration.md](./configuration.md)). The reason these values exist as literals here is so you can paste them into a config file as initial values, not so you can paste them into a header file.

---

## Sources

- AccessGrid DESFire application structures (TCI value, AIDs, keys, file layouts): https://www.accessgrid.com/guides/knowledgebase/accessgrid-desfire-application-structures
- Apple ECP2 frame structure (marker byte, version, configuration-byte bit layout, terminal type/subtype values, TCI semantics): https://github.com/kormax/apple-enhanced-contactless-polling
- Apple Wallet HCE preflight AIDs (`OSE.VAS.01`, `D2760000850100`): publicly documented in Apple's NFC reader-session entitlement reference and in community NFC tooling.
- NXP MIFARE DESFire EV1 specification: NXP AN0944 / AN0946.
- AN10922 (key diversification): https://www.nxp.com/docs/en/application-note/AN10922.pdf
- Pseudo-code walkthrough: [reference-implementation.md](./reference-implementation.md)

---

## Protocol stack

```
┌─ Application — credential bytes parsed (Wiegand 26/34/custom)
├─ DESFire EV1 — SELECT APPLICATION → AES auth → ReadData (Fully Encrypted CommMode)
├─ ISO 7816-4 (over HCE only) — SELECT BY NAME preflight for Apple Wallet
├─ ISO 14443A-4 — block-oriented transport
├─ ECP v2 — 6A-prefixed polling frame with TCI; wakes Apple Wallet
└─ NFC RF — 13.56 MHz, Type A
```

Two flavors of the DESFire layer ship from AccessGrid:

| Structure | AID (big-endian) | AID (wire, LE) | Read access | Notes |
|-----------|------------------|----------------|-------------|-------|
| **Simple** | `F5 64 01` | `01 64 F5` | Static read key | One key fits all passes |
| **Key Diversified** | `AC CE 55` | `55 CE AC` | Per-pass derived key | Read key is AN10922-derived from a privacy key + UID |

A reader that needs to handle both must try them in sequence: SELECT Simple → on `91 A0` (Application not found), SELECT Key Diversified → continue.

---

## Step 0 — ECP2 polling frame

Apple Wallet only presents an access pass when the reader transmits an ECP2 annotation frame. Without it, an Apple Wallet device in your field will not surface anything.

**TCI:** `02 00 00` (configurable; see [configuration.md](./configuration.md))

**Frame format** (ECP version 2, Access terminal type):

```
6A 02 C3 02 02 02 00 00
│  │  │  │  │  │  └──┴── TCI bytes (3 bytes)
│  │  │  │  └──┴── Terminal subtype = 0x02 (Access)
│  │  │  └── Terminal type = 0x02 (Access)
│  │  └── Configuration byte: 0b10000011 (bit 7=annotation present, bit 6=TRA=0, length=3)
│  └── ECP version = 2
└── ECP frame marker
```

If TRA (Transaction Required Acknowledgment) is set to 1 (no transaction required), bit 6 of the configuration byte becomes `1` → `0xC3` becomes `0x83`. Most access deployments leave TRA=true.

Send this frame in your poll loop alongside (or instead of) the standard ISO 14443A REQA. PCSC v2 transparent-mode readers expose this via the polling extensions; embedded frontends typically expose it via a "custom polling frame" register.

---

## Step 1 — Apple Wallet HCE preflight (ISO 7816 SELECT BY NAME)

**Only required for Apple Wallet devices (HCE).** Physical DESFire cards skip this.

Send two SELECT BY NAME APDUs in order — Apple Wallet uses the handshake to decide whether to expose the underlying DESFire HCE applet:

| # | AID (hex) | AID (ASCII) |
|---|-----------|-------------|
| 1 | `4F 53 45 2E 56 41 53 2E 30 31` | `OSE.VAS.01` |
| 2 | `D2 76 00 00 85 01 00` | (binary) |

APDU shape (both):

```
CLA  INS  P1  P2  Lc   Data         Le
00   A4   04  00  <n>  <AID bytes>  00
```

Responses are not used — they are purely a wake-up. The native DESFire SELECT APPLICATION (step 2) does the real selection. Both SW responses should be acknowledged but their contents can be discarded.

In firmware, this is just two extra APDUs in the activation sequence — issue them right after ISO 14443A-4 RATS / PPS completes and before the first DESFire native command. The NFC frontend's APDU pass-through (e.g. NXP NFC Reader Library `phpalI14443p4_Exchange`) handles them like any other ISO 7816 SELECT.

---

## Step 2 — DESFire SELECT APPLICATION

INS `5A`, data is the AID in little-endian wire form.

```
CLA  INS  P1  P2  Lc   Data       Le
90   5A   00  00  03   01 64 F5   00     ← Simple structure
90   5A   00  00  03   55 CE AC   00     ← Key Diversified
```

Success: `91 00`. Application not found: `91 A0`. Other failures: see DESFire EV1 status word table.

---

## Step 3 — Authenticate (DESFire EV1 AES three-pass)

INS `AA` for the initial AUTHENTICATE; INS `AF` for the CONTINUE frame.

### Step 3a — pick the key index

| Structure | Index | Key role |
|-----------|-------|----------|
| Simple | `01` | Read key — static AES-128 |
| Key Diversified | `02` first (Privacy) | To read UID |
| Key Diversified | `01` second | Read key — per-card, AN10922-derived |

### Step 3b — three-pass exchange

```
1. Reader → Card:  90 AA 00 00 01 <key_idx> 00
2. Card   → Reader: <enc_RndB>           SW = 91 AF   (16 bytes ciphertext)
3. Reader: RndB = AES-CBC-decrypt(key, enc_RndB, IV=zeros)
           RndA = 16 random bytes
           payload = RndA || rot_left_1(RndB)
           enc_payload = AES-CBC-encrypt(key, payload, IV=enc_RndB)
4. Reader → Card:  90 AF 00 00 20 <enc_payload> 00
5. Card   → Reader: <enc_rot_RndA>        SW = 91 00
6. Reader: rot_RndA = AES-CBC-decrypt(key, enc_rot_RndA, IV=last_16(enc_payload))
           verify rot_RndA == rot_left_1(RndA)   ← if not, abort
```

### Step 3c — derive session key

```
session_key = RndA[0:4] || RndB[0:4] || RndA[12:16] || RndB[12:16]
```

The session key protects all subsequent commands within this auth context. Re-authenticating with a different key replaces it.

---

## Step 4 (Key Diversified only) — derive the per-card read key

After authenticating with the Privacy key (index `02`), read the real UID via `GET_CARD_UID` (INS `51`) over the secure channel, then compute the diversified read key:

```
DiversifiedKey = AES128CMAC(
    PrivacyKey,
    0x01 || 0x02 || UID || AID || padding
)
```

Where:

- `PrivacyKey` is the static AES-128 key shown below (`fc26aab3c926c0028ce4c47c8a1b4afb`).
- `UID` is 7 bytes (14 hex chars) returned by the GET_CARD_UID call.
- `AID` is the application's wire-order AID (`55 CE AC` for Key Diversified).
- The input is zero-padded out to 16 bytes (CMAC requires block-aligned input; AES-128 block = 16 B).
- The result is a 16-byte key used as the index-01 read key for THIS specific card.

A useful config-file convention is to express the derived key as a templated string the reader evaluates at runtime, e.g.:

```
"aes128cmac(fc26aab3c926c0028ce4c47c8a1b4afb, 0102{uid}{aid}aaaaaa)"
```

…where `{uid}` and `{aid}` are filled in from the context (UID from `GET_CARD_UID`, AID from the SELECT step). This keeps the privacy key as the only secret in config and lets the reader derive the per-card key without ever storing it.

Then re-authenticate with INS `AA` / `AF` against key index `01`, using this derived key. Step 5 onward is the same as Simple structure.

---

## Step 5 — ReadData on file 00

INS `BD`. File 00 is a Standard File with CommMode = Fully Encrypted (option byte's low 2 bits = `11`).

**Command params:** `<file_id> <offset_3LE> <length_3LE>` → `00 00 00 00 20 00 00` for "read 32 bytes starting at offset 0 of file 0".

```
CLA  INS  P1  P2  Lc   Data                Le
90   BD   00  00  07   00 00 00 00 20 00 00   00
```

### Fully Encrypted CommMode mechanics

1. Compute `CMAC(session_key, INS || params, IV=zeros)` — this *advances* the running session IV. Use the resulting 16 bytes as the IV for decrypting the response. (Don't attach the MAC to the outbound APDU; in this mode the command is plain.)
2. The card responds with ciphertext, length = multiple of 16 bytes, plus `91 00` SW. The ciphertext is `AES-CBC-encrypt(session_key, plaintext, IV=ivForResponse)` where `plaintext` is `<file_bytes> || <CRC32_JAM(file_bytes || 0x00)> || <ISO9797-1 method 2 padding>`.
3. Decrypt with `AES-CBC-decrypt(session_key, ciphertext, iv=ivForResponse)`.
4. Strip ISO 9797-1 method 2 padding (find the last `0x80`; everything after must be `0x00`).
5. The trailing 4 bytes are a JAM-CRC32 (CRC32 with init=`0xFFFFFFFF`, no final XOR — *not* the same as ZIP CRC32). Verify it over `(plaintext || 0x00)`. If it doesn't match: wrong key or corrupted response.
6. The remaining bytes are the credential payload.

---

## Step 6 — Parse the credential payload

File 00 is 32 bytes (Simple) or up to 4096 bytes (Key Diversified). The default 32-byte layout when AccessGrid uses `site_code` + `card_number`:

```
Offset  Bytes   Meaning
0–2     00 00 00         padding
3       00                static
4       00                static
5       NN                bit count (e.g. 0x1A = 26 for Wiegand 26-bit)
6+      <card data>       raw card bits, MSB-first
…       00 00 …           padding to file size
```

**Sample payload:** `0000000000002A303D0000000000000000000000000000000000000000000000`
- bit count = `0x2A` = 42 bits, card data = `30 3D` (start of)

### Wiegand 26-bit decode

Card data is 4 bytes:

```
raw   = (b0<<24) | (b1<<16) | (b2<<8) | b3
parity_even = bit 25     (highest bit)
site_code   = (raw >> 17) & 0xFF
card_number = (raw >> 1)  & 0xFFFF
parity_odd  = bit 0      (lowest bit)
```

### Wiegand 34-bit decode

Card data is 5 bytes:

```
raw         = (b0<<32) | (b1<<24) | (b2<<16) | (b3<<8) | b4
site_code   = (raw >> 17) & 0xFFFF
card_number = (raw >> 1)  & 0xFFFF
```

### Custom (`file_data`-issued) payloads

If the issuer chose raw bytes instead of `site_code` + `card_number`, the file is 32–64 bytes of issuer-defined format. Hand them to the host as-is; you do not parse Wiegand semantics.

Example 37-bit credential: `20540008A0000000000000000000000000000000000000000000000000000000`

---

## Step 7 — End the session

After ReadData succeeds (or fails), close cleanly:

- DESFire native: nothing required — drop the field.
- ECP-tracked sessions (Apple Wallet variants reported via the `MIFARE_DESFIRE_APPLE_WALLET` software-subtype byte in `GetVersion`): send the ECP end-session command to release the wallet-side session cleanly. Check your reader IC's NFC stack for the exact INS — most vendor libraries (e.g. NXP NFC Reader Library) expose this as a named DESFire helper.

Then de-select / power down the RF field before the next poll.

---

## The literal AccessGrid keys

> **Do not paste these into firmware source. Paste them into your config file, then load that config into firmware at boot. See [configuration.md](./configuration.md).**

### Simple structure

| Index | Role | AES-128 key (hex) | Protects |
|-------|------|-------------------|----------|
| `00` | Master | `1869e1e47af074f4fcf76a4ba9cf0709` | All application-level operations |
| `01` | Read | `6e369e1a479c14601d2ed20a4121a67d` | File 00 read |

### Key Diversified structure

| Index | Role | AES-128 key (hex) | Protects |
|-------|------|-------------------|----------|
| `00` | Master | `a9f212b7a5c5e04d73af90524a437b39` | All application-level operations |
| `01` | Read (per-card, derived) | *AN10922-derived at runtime* | File 00 read on this specific card |
| `02` | Privacy | `fc26aab3c926c0028ce4c47c8a1b4afb` | Real-UID retrieval + key diversification source |

The Privacy key (index `02`) is the static input to the AN10922 CMAC; the result is the per-card index-`01` key. See Step 4 above.

---

## DESFire EV1 status word quick reference

| SW1 SW2 | Meaning |
|---------|---------|
| `91 00` | OK |
| `91 AF` | Additional frame (continue with INS `AF`) |
| `91 AE` | Authentication error |
| `91 7E` | Length error |
| `91 9D` | Permission denied (wrong key for this file) |
| `91 A0` | Application not found |
| `91 F0` | File not found |
| `91 1C` | Illegal command |

Status words use the `91 xx` family — not the ISO 7816 `90 00` family — when the card is in native DESFire mode.

---

## Common pitfalls

- **AID byte order.** Article shows `F56401` (big-endian, human-readable). Wire format is little-endian: `01 64 F5`. Convert once at config load.
- **Skipping the HCE preflight.** Apple Wallet won't expose the DESFire applet without the `OSE.VAS.01` / `D2760000850100` SELECT BY NAME calls. Physical cards don't need them; HCE does.
- **JAM-CRC32 vs ZIP CRC32.** Same polynomial (`0xEDB88320`), different init (`0xFFFFFFFF`), different final step (no XOR for JAM, XOR-with-`0xFFFFFFFF` for ZIP). Using the wrong one → CRC fails 50% of the time and you'll waste a day.
- **IV management.** First auth pass uses IV=zeros; second pass uses IV = ciphertext from pass 1; ReadData response uses IV = CMAC over `INS || params`. Get any of these wrong and decryption produces garbage.
- **Session key rotation between auths.** Every time you AUTHENTICATE, the session key resets. If you read multiple files with different read keys, each requires its own re-auth, and the session IV resets to zero each time.
- **Confusing Simple and Key Diversified structures.** They use different AIDs and different keys. A reader that can only handle Simple will fail on customers using Key Diversified, and vice versa. Configure for both unless you control the issuance side.
- **Hard-coding the keys.** Don't.

---

> **Reminder.** Read these keys, AIDs, and TCI bytes from runtime configuration — OSDP, config file, BLE provisioning, config app. Do **not** bake them into the firmware image. See [configuration.md](./configuration.md) for delivery patterns and key-storage guidance.
