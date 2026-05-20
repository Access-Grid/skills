# Reference Implementation (Pseudo-code)

A language-neutral walkthrough of a complete AccessGrid reader, written in C-shaped pseudo-code so it translates directly into the C or C++ that most reader firmware ships in. Read this alongside [apple-ecp2-desfire.md](./apple-ecp2-desfire.md), [google-smarttap.md](./google-smarttap.md), and [configuration.md](./configuration.md) — those carry the byte-level truth; this file shows how the pieces fit.

Variables in `cfg.*` are loaded from runtime configuration; **none of them are hard-coded literals**. See [configuration.md](./configuration.md).

---

## Notes for C / C++ firmware

The pseudo-code below assumes embedded-firmware conventions, not desktop or mobile-app conventions:

- **Return codes, not exceptions.** Every function returns a status enum (`AG_OK`, `AG_ERR_AUTH`, `AG_ERR_CRC`, `AG_ERR_TIMEOUT`, …). No `try` / `catch`. The host loop checks return values and surfaces failures to the access-control bus.
- **Buffer + length pairs, not opaque `Bytes` types.** Everywhere the pseudo-code says `bytes` or `payload`, in C that becomes `uint8_t *buf, size_t len`. Pre-allocate buffers — DESFire file payloads cap at 64 bytes for the AccessGrid Simple structure, 4096 bytes for Key Diversified; SmartTap responses chunk in ≤255-byte APDU windows. Sizes are bounded; you should not need heap allocation in the read path.
- **No malloc in the hot path.** Static buffers in the reader-task context. If your platform has heap available, fine — but if you're on a Cortex-M with 64 KB of RAM, every read uses the same scratch region.
- **Crypto primitives come from a vetted library.** Don't roll your own. Recommended:
    - **mbedTLS** — small, BSD-licensed, ubiquitous in embedded. Has AES-CBC/CTR, AES-CMAC, HMAC-SHA256, HKDF, ECDH/ECDSA on P-256.
    - **wolfSSL / wolfCrypt** — commercial-friendly, FIPS-validated options available.
    - **Silicon-vendor crypto APIs** — STM32 CRYP/HASH peripherals, NXP CAAM/CAU, Microchip TrustFLEX. Hardware-accelerated, lower CPU and power than software AES.
    - **Secure Element ECDH** — if you have an ATECC608A, SE050, or OPTIGA TPM on board, do the SmartTap long-term private key + ECDH inside the SE. The private key never enters firmware memory.
- **NFC frontend SDK does the radio work.** This file does not implement ISO 14443A activation, anticollision, RF field control, or APDU framing — your NFC IC's library handles that. Common choices:
    - **NXP NFC Reader Library** (PN5180 / PN7160 / RC663) — covers ECP frame transmission via `phpalI14443p3a_RequestA` extensions, DESFire EV1 secure channel helpers, APDU pass-through.
    - **libnfc** (PN532, ACR readers) — desktop / Linux prototyping; production firmware usually moves off this.
    - **Vendor RTOS drivers** — ELATEC, ST25R, ID3.
- **Endianness.** All AIDs and integers shown here are in human-readable big-endian. The wire usually wants little-endian for AIDs and big-endian for SmartTap collector ID. Convert at the boundary, never inside protocol logic.
- **Concurrency.** Most firmware reads run in a single reader task; if you have multiple antennas, run independent reader tasks with independent session state. No shared mutable state between them.

---

## Top-level loop

```
int main(void):
    Config cfg;
    if (load_config(&cfg) != AG_OK) panic();    // OSDP, file, BLE, config app

    NfcFrontend *nfc = nfc_open(&cfg.reader);
    HostBus     *bus = bus_open(&cfg.reader);   // OSDP / Wiegand / network output

    EcpFrame ecp;
    build_ecp2_frame(&cfg.annotation, &ecp);

    while (1):
        Tag tag;
        int rc = nfc_poll(nfc, &ecp, 100 /*ms*/, &tag);
        if (rc == AG_NO_TAG) continue;
        if (rc != AG_OK)     { log_err(rc); continue; }

        Credential cred;
        rc = read_credential(&tag, &cfg, &cred);
        if (rc == AG_OK):
            bus_emit(bus, &cred);
        else:
            log_err_with_uid(rc, tag.uid, tag.uid_len);   // never log credential bytes

        nfc_deselect(nfc, &tag);
```

---

## Dispatch: pick the right transport

```
int read_credential(Tag *tag, Config *cfg, Credential *out):
    int rc;

    // DESFire native is the fast path when the tag's SAK identifies as MIFARE.
    // Fall through to SmartTap on failure or non-MIFARE tags.
    if (tag_is_mifare_family(tag)):
        rc = read_desfire(tag, &cfg->desfire, out);
        if (rc == AG_OK) return AG_OK;
        if (rc != AG_ERR_APP_NOT_FOUND) log_warn(rc);
        // Fallthrough on app-not-found — device may be Google Wallet only.

    return read_smarttap(tag, &cfg->smart_tap, out);
```

---

## ECP2 polling frame builder

```
void build_ecp2_frame(AnnotationConfig *acfg, EcpFrame *out):
    uint8_t config_byte = 0x80 | (acfg->tci_len & 0x0F);   // bit 7 = annotation present
    if (!acfg->tra) config_byte |= 0x40;                   // bit 6 = TRA (see step 0 of apple-ecp2-desfire.md)

    out->bytes[0] = 0x6A;                  // ECP marker
    out->bytes[1] = 0x02;                  // ECP version 2
    out->bytes[2] = config_byte;
    out->bytes[3] = 0x02;                  // Terminal type = Access
    out->bytes[4] = 0x02;                  // Subtype       = Access
    memcpy(&out->bytes[5], acfg->tci, acfg->tci_len);
    out->len = 5 + acfg->tci_len;
```

Pass `out` into your NFC IC's polling frame slot. On PN5180 with the NFC Reader Library, this is fed through the polling-loop extension; on bare PN532 you assemble the frame manually before `InListPassiveTarget`.

---

## Apple ECP2 / DESFire flow

```
int read_desfire(Tag *tag, DesfireConfig *dcfg, Credential *out):
    int rc;

    // Step 1 — Apple Wallet HCE preflight. Skip for physical DESFire cards.
    if (tag_is_hce(tag)):
        send_select_by_name(tag, OSE_VAS_01, sizeof(OSE_VAS_01));
        send_select_by_name(tag, D2_76_00_00_85_01_00, 7);
        // Responses discarded; this is a wake-up handshake.

    // Step 2 — SELECT APPLICATION. Try each configured AID in order.
    DesfireStructure *selected = NULL;
    uint8_t aid_wire[3];
    for (int i = 0; i < dcfg->n_structures; i++):
        DesfireStructure *s = &dcfg->structures[i];
        reverse_bytes(s->aid, 3, aid_wire);              // BE config → LE wire
        Apdu rsp;
        if (desfire_select_app(tag, aid_wire, &rsp) == AG_OK):
            selected = s;
            break;
    if (selected == NULL) return AG_ERR_APP_NOT_FOUND;

    // Step 3 — Master key auth (required before any per-file operation).
    Session sess;
    rc = authenticate_aes(tag, &selected->keys[KEY_MASTER], &sess);
    if (rc != AG_OK) return rc;

    // Step 4 — Resolve the actual read key.
    uint8_t read_key[16];
    if (selected->is_diversified):
        // 4a. Switch to Privacy key (idx 02) to read the real UID.
        rc = authenticate_aes(tag, &selected->keys[KEY_PRIVACY], &sess);
        if (rc != AG_OK) return rc;

        uint8_t uid[7];
        rc = desfire_get_card_uid(&sess, uid);           // PLAIN cmd, FULL response
        if (rc != AG_OK) return rc;

        // 4b. Derive the per-card read key via AN10922.
        uint8_t cmac_input[16] = {0};
        cmac_input[0] = 0x01;
        cmac_input[1] = 0x02;
        memcpy(&cmac_input[2], uid, 7);
        memcpy(&cmac_input[9], aid_wire, 3);
        // remaining bytes are zero-padded
        aes128_cmac(selected->keys[KEY_PRIVACY].bytes, cmac_input, 16, read_key);

        // 4c. Re-authenticate against key idx 01 using the derived key.
        rc = authenticate_aes_with(tag, /*key_index=*/0x01, read_key, &sess);
    else:
        rc = authenticate_aes(tag, &selected->keys[KEY_READ], &sess);
    if (rc != AG_OK) return rc;

    // Step 5 — ReadData on file 00 in CommMode=Fully Encrypted.
    uint8_t payload[64];
    size_t  payload_len;
    rc = read_encrypted_file(&sess, /*file=*/0x00, /*off=*/0, /*len=*/32,
                             payload, sizeof(payload), &payload_len);
    if (rc != AG_OK) return rc;

    // Step 6 — Parse.
    return parse_desfire_payload(payload, payload_len, out);
```

### `authenticate_aes` — DESFire EV1 three-pass

```
int authenticate_aes_with(Tag *tag, uint8_t key_index, const uint8_t key[16], Session *out):
    Apdu rsp;
    int rc = desfire_cmd(tag, 0xAA, &key_index, 1, &rsp);
    if (rc != AG_OK || rsp.sw1 != 0x91 || rsp.sw2 != 0xAF || rsp.data_len != 16)
        return AG_ERR_AUTH;

    uint8_t zero_iv[16] = {0};
    uint8_t rndB[16];
    aes_cbc_decrypt(key, rsp.data, 16, zero_iv, rndB);

    uint8_t rndA[16];
    rng_fill(rndA, 16);                       // CSPRNG — use the silicon TRNG

    uint8_t payload[32];
    memcpy(&payload[0],  rndA, 16);
    rotate_left_1(rndB, &payload[16]);        // payload = RndA || rot_left_1(RndB)

    uint8_t enc_payload[32];
    aes_cbc_encrypt(key, payload, 32, /*iv=*/rsp.data, enc_payload);

    Apdu rsp2;
    rc = desfire_cmd(tag, 0xAF, enc_payload, 32, &rsp2);
    if (rc != AG_OK || rsp2.sw1 != 0x91 || rsp2.sw2 != 0x00 || rsp2.data_len != 16)
        return AG_ERR_AUTH;

    uint8_t rot_rndA[16];
    aes_cbc_decrypt(key, rsp2.data, 16, /*iv=*/&enc_payload[16], rot_rndA);

    uint8_t expected_rot[16];
    rotate_left_1(rndA, expected_rot);
    if (ct_memcmp(rot_rndA, expected_rot, 16) != 0)     // constant-time
        return AG_ERR_AUTH;

    // Session key per DESFire EV1 spec.
    memcpy(&out->key[0],  &rndA[0], 4);
    memcpy(&out->key[4],  &rndB[0], 4);
    memcpy(&out->key[8],  &rndA[12], 4);
    memcpy(&out->key[12], &rndB[12], 4);
    memset(out->iv, 0, 16);
    out->tag = tag;
    return AG_OK;
```

### `read_encrypted_file` — CommMode=Fully Encrypted

```
int read_encrypted_file(Session *sess, uint8_t file_id, uint32_t off, uint32_t len,
                        uint8_t *out, size_t out_cap, size_t *out_len):
    uint8_t params[7];
    params[0] = file_id;
    params[1] =  off        & 0xFF;
    params[2] = (off >>  8) & 0xFF;
    params[3] = (off >> 16) & 0xFF;
    params[4] =  len        & 0xFF;
    params[5] = (len >>  8) & 0xFF;
    params[6] = (len >> 16) & 0xFF;

    // CMAC over (INS || params) advances the running session IV. The MAC
    // output IS the IV used to decrypt the response — we don't attach it to
    // the outbound APDU in Fully Encrypted mode.
    uint8_t cmac_input[8];
    cmac_input[0] = 0xBD;
    memcpy(&cmac_input[1], params, 7);
    uint8_t iv_for_response[16];
    aes128_cmac_iv(sess->key, sess->iv, cmac_input, 8, iv_for_response);
    memcpy(sess->iv, iv_for_response, 16);

    Apdu rsp;
    int rc = desfire_cmd(sess->tag, 0xBD, params, 7, &rsp);
    if (rc != AG_OK || rsp.sw1 != 0x91 || rsp.sw2 != 0x00) return AG_ERR_READ;
    if (rsp.data_len == 0 || (rsp.data_len % 16) != 0)      return AG_ERR_LENGTH;

    uint8_t padded[256];
    aes_cbc_decrypt(sess->key, rsp.data, rsp.data_len, iv_for_response, padded);

    size_t unpadded_len;
    if (iso9797_method2_strip(padded, rsp.data_len, &unpadded_len) != 0)
        return AG_ERR_PADDING;
    if (unpadded_len < 4) return AG_ERR_LENGTH;

    size_t plain_len     = unpadded_len - 4;
    const uint8_t *recv  = &padded[plain_len];
    uint8_t expected[4];
    jam_crc32_over(padded, plain_len, /*status_byte=*/0x00, expected);
    if (ct_memcmp(recv, expected, 4) != 0) return AG_ERR_CRC;

    if (plain_len > out_cap) return AG_ERR_BUFFER;
    memcpy(out, padded, plain_len);
    *out_len = plain_len;
    return AG_OK;
```

### `parse_desfire_payload` — Wiegand / custom

```
int parse_desfire_payload(const uint8_t *bytes, size_t len, Credential *out):
    // Layout: 00 00 00 00 00 <bit_count> <card_bits...> <zero padding>
    if (len < 6) return AG_ERR_LENGTH;
    if (bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 0):
        uint8_t bit_count   = bytes[5];
        const uint8_t *data = &bytes[6];
        size_t data_len     = len - 6;
        switch (bit_count):
            case 26: return wiegand26_decode(data, data_len, out);   // site 8b, card 16b
            case 34: return wiegand34_decode(data, data_len, out);   // site 16b, card 16b
            default: return raw_credential(data, data_len, bit_count, out);
    else:
        // Issuer-defined custom payload (file_data path).
        return raw_credential(bytes, len, /*bit_count=*/0, out);
```

---

## Google SmartTap flow

```
int read_smarttap(Tag *tag, SmartTapConfig *scfg, Credential *out):
    // Step 1 — SELECT SmartTap 2.0 application.
    Apdu rsp;
    int rc = iso7816_select_by_name(tag, scfg->aid, scfg->aid_len, &rsp);
    if (rc != AG_OK || rsp.sw1 != 0x90 || rsp.sw2 != 0x00) return AG_ERR_SELECT;

    uint8_t device_nonce[32];
    if (extract_handset_nonce(rsp.data, rsp.data_len, device_nonce) != 0)
        return AG_ERR_PARSE;

    // Step 2 — NEGOTIATE secure channel.
    uint8_t reader_nonce[32];
    uint8_t session_id[8];
    rng_fill(reader_nonce, 32);
    rng_fill(session_id,    8);

    EcKey reader_eph;
    ec_p256_keygen(&reader_eph);              // ephemeral — fresh per tap
    uint8_t reader_eph_pub[33];
    ec_p256_compressed(&reader_eph.pub, reader_eph_pub);

    uint8_t collector_id_be[4];
    u32_to_be(scfg->collector_id, collector_id_be);

    LongTermKey *lt = smart_tap_highest_version(scfg);
    uint8_t data_to_sign[32 + 32 + 4 + 33];
    memcpy(&data_to_sign[0],     reader_nonce,    32);
    memcpy(&data_to_sign[32],    device_nonce,    32);
    memcpy(&data_to_sign[64],    collector_id_be,  4);
    memcpy(&data_to_sign[68],    reader_eph_pub,  33);

    uint8_t signature[72];                    // P-256 DER-encoded ECDSA sig, ≤ 72 B
    size_t  sig_len;
    rc = ecdsa_p256_sha256_sign(lt, data_to_sign, sizeof(data_to_sign), signature, &sig_len);
    if (rc != AG_OK) return rc;

    uint8_t negotiate_msg[256];
    size_t  nmsg_len;
    build_negotiate_ndef(reader_nonce, reader_eph_pub, signature, sig_len,
                         collector_id_be, lt->version,
                         /*seq=*/0, session_id,
                         negotiate_msg, &nmsg_len);

    Apdu nrsp;
    rc = iso7816_cmd(tag, /*cla=*/0x90, /*ins=*/0x53, /*p1=*/0, /*p2=*/0,
                     negotiate_msg, nmsg_len, &nrsp);
    if (rc != AG_OK || nrsp.sw1 != 0x90 || nrsp.sw2 != 0x00) return AG_ERR_NEGOTIATE;

    uint8_t device_eph_pub[33];
    if (extract_handset_eph_pub(nrsp.data, nrsp.data_len, device_eph_pub) != 0)
        return AG_ERR_PARSE;

    // Step 3 — Derive session keys.
    EcPoint device_eph_uncompressed;
    ec_p256_decompress(device_eph_pub, &device_eph_uncompressed);

    uint8_t shared[32];
    ec_p256_ecdh(&reader_eph.priv, &device_eph_uncompressed, shared);

    uint8_t info[sizeof(data_to_sign) + 72];
    size_t  info_len = sizeof(data_to_sign) + sig_len;
    memcpy(info,                            data_to_sign, sizeof(data_to_sign));
    memcpy(&info[sizeof(data_to_sign)],     signature,    sig_len);

    uint8_t okm[48];
    hkdf_sha256(shared, 32, device_eph_pub, 33, info, info_len, okm, 48);

    uint8_t aes_key[16];
    uint8_t hmac_key[32];
    memcpy(aes_key,  &okm[0],  16);
    memcpy(hmac_key, &okm[16], 32);

    // Wipe sensitive intermediates as soon as we're done with them.
    secure_zero(shared, 32);
    secure_zero(okm,    48);

    // Step 4 — GET DATA (may chunk).
    uint8_t get_data_msg[64];
    size_t  gd_len;
    build_get_data_ndef(collector_id_be, /*seq=*/1, session_id,
                        get_data_msg, &gd_len);

    uint8_t buf[2048];                                  // upper bound on bundle
    size_t  buf_len = 0;
    rc = iso7816_cmd(tag, 0x90, 0x50, 0, 0, get_data_msg, gd_len, &rsp);
    while (rc == AG_OK):
        if ((rsp.sw1 != 0x90 && rsp.sw1 != 0x91) || rsp.sw2 != 0x00) return AG_ERR_GET_DATA;
        if (buf_len + rsp.data_len > sizeof(buf)) return AG_ERR_BUFFER;
        memcpy(&buf[buf_len], rsp.data, rsp.data_len);
        buf_len += rsp.data_len;
        if (rsp.sw1 == 0x90) break;
        rc = iso7816_cmd(tag, 0x90, 0xC0, 0, 0, NULL, 0, &rsp);    // GET RESPONSE
    if (rc != AG_OK) return rc;

    // Step 5 — Decrypt and verify.
    const uint8_t *bundle;
    size_t bundle_len;
    if (extract_record_bundle(buf, buf_len, &bundle, &bundle_len) != 0)
        return AG_ERR_PARSE;

    uint8_t flags = bundle[0];
    const uint8_t *payload = &bundle[1];
    size_t payload_len = bundle_len - 1;

    uint8_t decrypted[2048];
    if (flags & FLAG_ENCRYPTED):
        if (payload_len < 12 + 32) return AG_ERR_LENGTH;
        const uint8_t *iv         = &payload[0];
        const uint8_t *ciphertext = &payload[12];
        size_t         ct_len     = payload_len - 12 - 32;
        const uint8_t *tag_mac    = &payload[payload_len - 32];

        uint8_t expected_mac[32];
        hmac_sha256_two(hmac_key, 32, iv, 12, ciphertext, ct_len, expected_mac);
        if (ct_memcmp(expected_mac, tag_mac, 32) != 0) return AG_ERR_HMAC;

        uint8_t counter_iv[16] = {0};
        memcpy(counter_iv, iv, 12);                   // 12-byte IV + 4 zero bytes
        aes_ctr_decrypt(aes_key, counter_iv, ciphertext, ct_len, decrypted);
        payload = decrypted;
        payload_len = ct_len;

    uint8_t inflated[4096];
    if (flags & FLAG_COMPRESSED):
        size_t inflated_len;
        if (zlib_inflate(payload, payload_len, inflated, sizeof(inflated), &inflated_len) != 0)
            return AG_ERR_PARSE;
        payload = inflated;
        payload_len = inflated_len;

    // Wipe session keys before returning — they were tap-scoped.
    secure_zero(aes_key,  16);
    secure_zero(hmac_key, 32);

    // Step 6 — Parse Customer / Pass objects.
    return parse_record_bundle(payload, payload_len, out);
```

---

## Notes on the pseudo-code

- **Crypto primitives** — `aes_cbc_*`, `aes128_cmac`, `aes128_cmac_iv` (CMAC with a non-zero starting IV — most libraries call this "MAC chained" or accept an IV parameter), `aes_ctr_decrypt`, `hmac_sha256`, `hkdf_sha256`, `ec_p256_*`, `ecdsa_p256_sha256_sign`, `jam_crc32_over` — call these from mbedTLS, wolfCrypt, or your vendor's hardware crypto driver. **Do not implement them yourself.**
- **`ct_memcmp`** — constant-time byte comparison (`mbedtls_ct_memcmp` in mbedTLS 3.x, hand-rolled OR-fold loop otherwise). Plain `memcmp` early-exits on first mismatch and leaks timing.
- **`secure_zero`** — must not be optimized away. Use `mbedtls_platform_zeroize`, `wolfCrypt`'s `ForceZero`, or C11's `memset_s`. Compilers WILL remove naked `memset(secret, 0, sizeof(secret))` if they can prove `secret` is dead.
- **`rng_fill`** — must use a cryptographically-secure RNG. The MCU's hardware TRNG (STM32 `RNG`, NXP `TRNG`, etc.) is the right source. Never `rand()`.
- **Config access** — `dcfg->structures[i]` and `selected->keys[KEY_READ]` assume the loader has materialized config into structs at boot. Multiple keys per index is the rotation pattern; iterate until one authenticates. See [configuration.md](./configuration.md).
- **Status word handling** — every APDU function returns `(data, sw1, sw2)`. The illustrative checks here map directly to typed error codes; production firmware logs the SW pair alongside the error.
- **Session state** — DESFire `Session` carries the session key and the running IV. Every authenticated command consumes / updates the IV. Each new `authenticate_aes_with` resets it.
- **Buffer sizes** — the literals above (`64`, `256`, `2048`, `4096`) are upper bounds for AccessGrid-issued credentials and typical SmartTap bundles. Audit against the largest payload you expect to encounter; size your scratch buffers once at compile time.
- **No literals from config in this file.** Every TCI byte, AID, key, and collector ID would be loaded from `cfg`. The hex values are in [apple-ecp2-desfire.md](./apple-ecp2-desfire.md) for the protocol reference, and in your config file for the runtime.

---

## What this pseudo-code does NOT cover

- **NFC physical layer** — RF field control, ISO 14443A activation, anticollision, ATS / PPS exchange. Your NFC frontend SDK owns these. The pseudo-code starts after activation and ends before the next poll.
- **OSDP / Wiegand output formatting** — host-specific; out of scope for the read side.
- **Multi-antenna / multi-reader concurrency** — each reader-task runs the loop above independently.
- **Power management** — sleeping between polls, waking on RF detect (PN5180 LPCD), etc. NFC IC vendor docs cover this.
- **Firmware update mechanism** — orthogonal to the read flow but should respect the config-driven principle (config survives FW updates; keys never live in the FW image).
- **OSDP Secure Channel** — used to deliver config and report events; outside the credential-read flow itself.

---

## Verification checklist

When porting the pseudo-code into your firmware, verify each of these against a known-good test card (provision sample passes in both DESFire structures from AccessGrid):

- [ ] ECP2 frame bytes match exactly for your configured TCI and TRA settings.
- [ ] HCE preflight SELECT BY NAME sequences both fire before the native DESFire SELECT.
- [ ] DESFire SELECT APPLICATION accepts both AIDs (Simple `01 64 F5` and Diversified `55 CE AC` on the wire).
- [ ] AES three-pass auth completes against the master key for both structures.
- [ ] Session key derivation matches: `RndA[0:4] || RndB[0:4] || RndA[12:16] || RndB[12:16]`.
- [ ] AN10922 derivation produces a key that successfully authenticates index 01 on a diversified pass.
- [ ] CMAC-over-(INS || params) IV produces correct decryption of file 00 ciphertext.
- [ ] JAM-CRC32 (init=`0xFFFFFFFF`, no final XOR) over (plaintext || `0x00`) matches the trailing 4 bytes.
- [ ] Wiegand 26-bit and 34-bit decoders return correct site code + card number against known test values.
- [ ] SmartTap NEGOTIATE succeeds with your registered collector_id and long-term public key.
- [ ] HKDF salt is the exact 33-byte compressed device ephemeral pubkey received.
- [ ] HMAC is verified *before* AES-CTR decryption — and verified with constant-time comparison.
- [ ] zlib inflate applied only when `FLAG_COMPRESSED` is set.
- [ ] Stack high-water mark in the reader task fits inside your allocated stack with margin.
- [ ] `secure_zero` actually clears the scratch buffers — confirm via debugger after a tap.
- [ ] Reader recovers from RF-field-removed-mid-transaction by tearing down state and returning to poll.

Once all of these pass on a bench, run the field-test checklist from SKILL.md Phase 7.
