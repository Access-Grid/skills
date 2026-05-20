# Google SmartTap Reader Implementation

Google Wallet exposes AccessGrid credentials over Google's SmartTap 2.0 protocol. The reader negotiates an ephemeral encrypted channel using ECDH on the P-256 curve, then issues a single GET DATA command to retrieve the (encrypted, possibly compressed) record bundle.

> **Config-driven reminder.** Your reader-specific `collector_id` and long-term EC P-256 private key are the most sensitive secrets in your firmware after the DESFire AES keys. **They must not live in the firmware binary.** Load them from OSDP, a config file, a config app, or BLE provisioning. See [configuration.md](./configuration.md).

---

## Sources

- Google SmartTap 2.0 specification (NDA — request via Google Pay Business).
- AccessGrid docs: https://accessgrid.com/docs
- Pseudo-code walkthrough: [reference-implementation.md](./reference-implementation.md)

---

## Protocol stack

```
┌─ Application — parsed Customer / Pass objects
├─ NDEF + record bundle parser (zlib decompress optional)
├─ AES-128-CTR decryption + HMAC-SHA256 integrity
├─ HKDF-SHA256 — derive session keys from ECDH shared secret
├─ ECDSA-P-256 signature (long-term reader key signs ephemeral pub + nonces)
├─ SmartTap 2.0 application protocol (NEGOTIATE, GET DATA)
├─ ISO 7816-4 SELECT BY NAME
├─ ISO 14443A-4 transport
└─ NFC RF — 13.56 MHz, Type A
```

Unlike Apple's transport, SmartTap does **not** use an ECP polling frame. Standard ISO 14443A REQA / activation is sufficient — the phone is in HCE and responds when polled.

---

## Reader enrollment (one-time, per reader unit)

Before any reader can decrypt SmartTap traffic, AccessGrid needs to know two things about it:

1. **A 4-byte `collector_id`** — assigned by AccessGrid when you register the reader (or reader fleet).
2. **A long-term ECDSA P-256 public key** — the matching private key stays on the reader.

You generate the keypair, send the public key to AccessGrid, and AG associates `(collector_id, public_key, key_version)` with passes that should be readable by your fleet.

Key generation example (one-time, off-line):

```bash
openssl ecparam -name prime256v1 -genkey -noout -out reader-lt.pem
openssl ec -in reader-lt.pem -pubout -out reader-lt.pub
```

Send `reader-lt.pub` to AccessGrid. Keep `reader-lt.pem` (or its DER form) safe — see [configuration.md](./configuration.md) for storage.

Multiple key versions can coexist for rolling rotation; configure them with integer `key_version` identifiers, e.g. `53` in the reference impl.

---

## Step 1 — SELECT SmartTap 2.0 application

**AID:** `A0 00 00 04 76 D0 00 01 11`

APDU:

```
CLA  INS  P1  P2  Lc   Data                       Le
00   A4   04  00  09   A0 00 00 04 76 D0 00 01 11  00
```

Success: `90 00`. The response data is a BER-TLV FCI template containing — among other fields — an NDEF message with the **device nonce** (a record of type `SmartTapNDEFType.HANDSET_NONCE`). Save the device nonce; you'll sign it in step 2.

Failure: any other SW. Likely causes — phone has no AccessGrid pass installed, wallet locked, wrong AID.

---

## Step 2 — NEGOTIATE secure channel

This is the only round-trip that signs anything with your long-term key. The output is a shared AES + HMAC key pair valid for this tap.

### Reader-side preparation

1. **Generate an ephemeral EC P-256 keypair** (per tap, never reused).
2. **Generate a 32-byte reader nonce** (`reader_nonce`) and an 8-byte session ID (`session_id`).
3. **Extract the device nonce** from the FCI in step 1.
4. **Build the data-to-sign** by concatenating these four byte strings, in order:
   ```
   data_to_sign = reader_nonce || device_nonce || collector_id || reader_ephemeral_pub
   ```
   - `reader_nonce`: 32 bytes
   - `device_nonce`: 32 bytes (from step 1)
   - `collector_id`: 4 bytes, **big-endian** representation of the integer
   - `reader_ephemeral_pub`: **compressed** P-256 point (33 bytes, X9.62 format starting with `0x02` or `0x03`)
5. **Sign with the long-term key**:
   ```
   signature = ECDSA-SHA256(long_term_private_key, data_to_sign)
   ```
6. **Build the NEGOTIATE NDEF message** containing `reader_nonce`, `reader_ephemeral_pub`, `signature`, `collector_id`, key version, sequence number, session ID.

### Send the APDU

```
CLA  INS  P1  P2  Lc   Data                Le
90   53   00  00  <n>  <NEGOTIATE NDEF>    00
```

### Response

Success: `90 00`. The response is an NDEF message containing the **device ephemeral public key** (record type `HANDSET_EPHERMAL_PUBLIC_KEY`) — 33 bytes, compressed P-256 point.

Failure SWs to expect:
- `95 00` = `COLLECTOR_AUTHENTICATION_FAILED` — signature didn't verify, or the phone doesn't know your collector ID. Usually means the wrong long-term key or unregistered reader.
- `69 85` = `CONDITIONS_OF_USE_NOT_SATISFIED` — wallet locked or no qualifying pass.

---

## Step 3 — Derive session keys

### ECDH

Decompress the device's ephemeral public key (use your crypto library's `from_encoded_point` helper). Then:

```
shared_secret = ECDH(reader_ephemeral_priv, device_ephemeral_pub)   // 32 bytes
```

### HKDF-SHA256

Derive 48 bytes of keying material:

```
okm = HKDF-SHA256(
    ikm   = shared_secret,
    salt  = device_ephemeral_pub_bytes,      // the 33-byte compressed point
    info  = data_to_sign || signature,       // exact bytes from step 2
    L     = 48,
)

aes_key  = okm[0:16]    // 128-bit AES key
hmac_key = okm[16:48]   // 256-bit HMAC key
```

Both keys are valid for this tap only. Discard at the end.

---

## Step 4 — GET DATA

```
CLA  INS  P1  P2  Lc   Data            Le
90   50   00  00  <n>  <GET DATA NDEF>  00
```

The `<GET DATA NDEF>` carries `collector_id`, `sequence_number`, `session_id`.

### Multi-part responses

SmartTap may chunk the response. Loop:

- If SW = `90 00` → done, append data and break.
- If SW = `91 00` (`MORE_DATA_AVAILABLE`) → append data, send `GET RESPONSE` (`90 C0 00 00 00`), continue.
- Other SW → fail.

### Parse the outer NDEF

The accumulated bytes are an NDEF message. Drill in:

```
service_response  = ndef.find_by_type("SERVICE_RESPONSE").value_to_message()
record_bundle     = service_response.find_by_type("RECORD_BUNDLE").payload

flags    = record_bundle[0]                  // see RecordBundleFlags
payload  = record_bundle[1:]
```

### Flags

```
ENCRYPTED   = 0x01   // payload is AES-CTR encrypted with HMAC trailer
COMPRESSED  = 0x02   // (post-decrypt) payload is zlib-deflated
```

Other bits may appear; ignore unknowns rather than rejecting.

---

## Step 5 — Decrypt and verify

If `ENCRYPTED` flag is set:

```
const uint8_t *iv         = &payload[0];                       // 12-byte nonce
const uint8_t *ciphertext = &payload[12];                      // middle
size_t         ct_len     = payload_len - 12 - 32;
const uint8_t *hmac_tag   = &payload[payload_len - 32];        // last 32 bytes

// HMAC integrity check — DO NOT DECRYPT IF THIS FAILS
uint8_t expected_hmac[32];
hmac_sha256_two(hmac_key, 32, iv, 12, ciphertext, ct_len, expected_hmac);
if (ct_memcmp(expected_hmac, hmac_tag, 32) != 0) return AG_ERR_HMAC;

// AES-128-CTR decrypt.
// CTR initial counter block = iv (12 bytes) || 00 00 00 00 (4 zero counter bytes)
uint8_t counter_iv[16] = {0};
memcpy(counter_iv, iv, 12);
aes_ctr_decrypt(aes_key, counter_iv, ciphertext, ct_len, plaintext);
```

Always verify the HMAC **before** trusting the ciphertext. Use a constant-time comparison (`mbedtls_ct_memcmp`, `wolfSSL_CRYPTO_memcmp`, or a hand-rolled OR-fold loop) — plain `memcmp` early-exits on first mismatch and leaks timing.

If `COMPRESSED` flag is also set:

```
size_t inflated_len;
if (zlib_inflate(plaintext, ct_len, inflated, sizeof(inflated), &inflated_len) != 0)
    return AG_ERR_PARSE;
plaintext = inflated;
```

mbedTLS doesn't bundle zlib — use miniz or the standard zlib library; both work in embedded environments.

---

## Step 6 — Parse the plaintext record bundle

The decrypted plaintext is another NDEF message. Each record is a `SmartTapObject` — either a `Customer` or a `Pass`.

```c
typedef enum {
    SVC_ISSUER_UNSPECIFIED = 0,
    SVC_ISSUER_MERCHANT    = 1,
    SVC_ISSUER_WALLET      = 2,
    SVC_ISSUER_MANUFACTURER = 3,
} ServiceIssuer;

typedef struct {
    uint8_t       issuer_id[8];        // who issued the pass (e.g., AccessGrid)
    size_t        issuer_id_len;
    ServiceIssuer issuer_type;
    uint8_t       customer_id[32];     // opaque per-customer identifier
    size_t        customer_id_len;
    uint8_t       tap_id[16];          // per-tap unique ID — use for dedupe / replay protection
    size_t        tap_id_len;
    char          language[8];         // ISO 639-1, e.g. "en"
} Customer;

typedef struct {
    uint8_t       issuer_id[8];
    size_t        issuer_id_len;
    ServiceIssuer issuer_type;
    char          type[32];            // pass type string
    uint8_t       object_id[32];       // AG object ID
    size_t        object_id_len;
    char          message[128];        // optional message
} Pass;
```

Buffer sizes are illustrative — audit against the longest issuer IDs / messages you'll see and adjust at compile time. None of these need to live in dynamic memory.

For access control, the fields you typically care about are `customer_id` (who) and `tap_id` (which tap, for dedupe).

---

## Status word quick reference

| SW1 SW2 | Name | Meaning |
|---------|------|---------|
| `90 00` | `OK` | Success |
| `90 01` | `NO_PASSES` | Phone has no SmartTap passes |
| `90 02` | `PRE_SIGNED_AUTH` | Pre-signed authentication path |
| `91 00` | `MORE_DATA_AVAILABLE` | Continue with `GET RESPONSE` |
| `93 02` | `USER_SHOULD_SELECT_CARD` | Phone wants user to choose between multiple passes |
| `94 06` | `TOO_MANY_REQUESTS` | Rate-limited by phone |
| `95 00` | `COLLECTOR_AUTHENTICATION_FAILED` | Signature didn't verify; wrong LT key or unregistered collector |
| `69 85` | `CONDITIONS_OF_USE_NOT_SATISFIED` | Wallet locked, pass disabled, etc. |

These are the documented values; treat anything else as a transient failure and surface it to logs.

---

## Common pitfalls

- **Reusing the ephemeral key.** Generate a fresh P-256 keypair *per tap*. Reusing it breaks forward secrecy and may cause AG-side rejections.
- **Wrong byte order on collector ID.** It is a 32-bit integer in **big-endian** when sent on the wire.
- **Wrong compressed-point format on the ephemeral pub key.** Use X9.62 compressed (33 bytes starting `0x02` or `0x03`), not uncompressed (65 bytes starting `0x04`). HKDF salt is the same compressed-point bytes you sent.
- **Verifying the HMAC after decrypting.** Always verify first. Decrypting unverified ciphertext leaks information to padding-oracle-style attackers.
- **Constant-time HMAC comparison.** Use a constant-time byte comparison (`mbedtls_ct_memcmp`, `wolfSSL_CRYPTO_memcmp`, OpenSSL's `CRYPTO_memcmp`, or a hand-rolled loop that ORs every byte difference and only branches at the end). Plain `memcmp` (or `==`) leaks timing on early mismatch and lets attackers forge MACs one byte at a time.
- **AES-CTR counter encoding.** The IV/nonce is 12 bytes; pad to a 16-byte counter block with 4 zero bytes. Don't increment manually — the AES-CTR primitive handles per-block counter increments.
- **Skipping zlib.** The `COMPRESSED` flag is independent of `ENCRYPTED`. Plaintext may still be compressed.
- **Treating `91 00` as an error.** It means "more data available" in this protocol, even though many other ISO 7816 stacks use `91 xx` as native-error territory.
- **Hard-coding the collector ID or LT key.** They will rotate. They need to be reissued when a reader is RMA'd or repurposed. Bake them into config.

---

> **Reminder.** Your `collector_id` and long-term EC P-256 private key are reader-specific and must be loadable at runtime from your config plumbing. They are not AccessGrid-wide constants like the DESFire keys — they are tied to your specific reader unit (or reader fleet) and they will rotate. See [configuration.md](./configuration.md).
