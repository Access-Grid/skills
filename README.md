# accessgrid.com-skills

Open-source skill pack for AccessGrid integrations.

## Included Skills

### [`integrate-accessgrid`](./skills/integrate-accessgrid/)

For software engineers (and the AI agents helping them) adding AccessGrid mobile wallet credentials to an existing product. Walks a host codebase through seven phases: language and SDK selection, design session (one of four integration levels — MVP / Essential / Complete / Premium — plus UI/API choice), database discovery against four canonical concepts (Credential Holders, Credentials, Credential Formats, Event Logs), migrations, secrets and client wiring, endpoints and lifecycle, and webhook handling. Per-language references for the seven officially-supported SDKs (JavaScript/TypeScript, Ruby, Go, Python, C#/.NET, Java, PHP) plus a porting guide for stacks without an official SDK.

Snapshots three canonical AccessGrid articles (pass state transitions, image-dimension requirements, webhook event catalog) and the API authentication scheme (HMAC-SHA256, `X-ACCT-ID` / `X-PAYLOAD-SIG`) so the skill is self-contained.

### [`read-accessgrid-credential`](./skills/read-accessgrid-credential/)

For firmware and hardware teams (and the AI agents helping them) building NFC readers that consume AccessGrid mobile wallet credentials. Covers both transports:

- **Apple ECP2 / DESFire** — ECP v2 polling frame, Apple Wallet HCE preflight, DESFire EV1 native commands, AES three-pass auth, AN10922 key diversification, encrypted ReadData with CMAC-chained IV and JAM-CRC32 verify, Wiegand payload parsing.
- **Google SmartTap** — SmartTap 2.0 SELECT, NEGOTIATE (ECDSA-P-256 signing with a reader-held long-term key), ECDH + HKDF-SHA256 session keys, encrypted record bundle with AES-CTR + HMAC-SHA256.

Includes a C-shaped pseudo-code reference implementation for both transports, configuration guidance (the **config-driven principle**: TCI, AIDs, AES keys, SmartTap collector ID, and the long-term EC private key must all be loadable via OSDP / config file / config app / BLE provisioning, never baked into the firmware image), and per-framework storage tier guidance (TPM, Secure Element, encrypted flash).

## Repo Layout

```
skills/
├── integrate-accessgrid/
│   ├── SKILL.md                 ← phased flow + non-negotiables
│   ├── references/
│   │   ├── api-authentication.md
│   │   ├── database-discovery.md
│   │   ├── discovery-and-planning.md
│   │   ├── image-dimensions.md
│   │   ├── integration-{mvp,essential,complete,premium}.md
│   │   ├── no-sdk-porting.md
│   │   ├── pass-state-transitions.md
│   │   ├── webhook-events.md
│   │   └── {python,node-typescript,ruby-on-rails,go,java,csharp,laravel-php}.md
│   └── agents/
│
└── read-accessgrid-credential/
    ├── SKILL.md                 ← orientation + 7 implementation phases
    └── references/
        ├── apple-ecp2-desfire.md
        ├── google-smarttap.md
        ├── configuration.md
        └── reference-implementation.md
```

Every skill is a directory containing a `SKILL.md` (the entry point, with frontmatter the agent runtime reads) plus a `references/` directory holding topic-specific deep dives the SKILL.md links to as needed.

## Design Notes

- **Decision routing first, then task checklists, then acceptance criteria.** Skills are written so an agent (or a human) can land on `SKILL.md`, get oriented, and follow the path to the relevant reference without reading the entire pack.
- **Volatile implementation details link to canonical docs.** SDK install commands, AccessGrid API specifics, and protocol byte sequences from public sources are snapshotted with a re-fetch note; nothing is duplicated when an authoritative source exists.
- **Config-driven beats hard-coded.** Both skills push back against baking secrets, IDs, or platform-specific knobs into source code — `integrate-accessgrid` enforces this for AG account / SDK keys and webhook bearers; `read-accessgrid-credential` enforces it for TCI, AIDs, AES keys, and the SmartTap long-term private key.
- **Skill content is auditable for confidentiality.** All Apple-ECP2-related content cites public sources ([kormax/apple-enhanced-contactless-polling](https://github.com/kormax/apple-enhanced-contactless-polling)); no NDA-derived material.

## Contributing

Skills are markdown plus optional supporting files (scripts, agent configs). New skills go under `skills/<name>/`. Keep `SKILL.md` under ~250 lines as the entry point; push depth into `references/`.
