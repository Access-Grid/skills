# Discovery And Planning

Use this file when starting work in a host PACS or credentialing repo.

## Repo Inspection Checklist

Find these before coding:

- User or cardholder model
- Credential, badge, or card model
- Tenant, site, building, or organization model
- Where external-provider clients live
- Where secrets and env vars are defined
- Where queues, jobs, workers, or cron processes live
- Where webhook controllers or callback handlers live
- Where admin or issuance UI lives
- Where audit logs, activity logs, or event records live
- Where integration docs or ADRs belong

Useful searches:

```bash
rg -n "webhook|callback|signature|HMAC|job|worker|queue|retry"
rg -n "credential|badge|cardholder|site code|facility code|card number"
rg -n "twilio|sendgrid|postmark|stripe|external api|client"
rg -n "tenant|site|organization|building|campus"
```

## Routing Matrix

### Choose `simple`

Choose this when:

- Existing AccessGrid templates already exist
- The host app only needs issue, suspend, resume, and delete
- A manual setup step in AccessGrid is acceptable

Avoid this track if the product must self-serve tenant onboarding.

### Choose `comprehensive`

Choose this when:

- The host app must manage templates or landing pages
- A cloud product needs webhook-driven reconciliation
- Multi-tenant config should live in the host app rather than in a console checklist

### Choose `deep`

Choose this when:

- Credential profile automation is required
- Secure key lifecycle is part of the product scope
- Support and operations need auditable reissue and troubleshooting paths

Do not choose this track just because the API allows it.

## Required Inputs

Collect or confirm:

- `ACCOUNT_ID`
- `SECRET_KEY`
- webhook verification inputs returned or required by the active AccessGrid webhook configuration
- AccessGrid environment or base URL if applicable
- Existing template IDs or template strategy
- Existing landing page IDs or landing page strategy
- Host primary key used for the credential
- Credential data source format
- Wallet art assets or explicit placeholder approval

## Delivery Artifacts

Create these in the host repo or its existing documentation structure:

1. Entity mapping document
2. Config and secrets contract
3. Lifecycle state map
4. Retry and dedupe policy
5. Verification log

## AccessGrid Terms To Preserve

Use the official docs vocabulary when writing integration code or docs:

- `Access Pass`: the wallet credential product name in docs
- `access_cards` or `AccessCards`: the SDK surface used for pass lifecycle methods
- `console`: the SDK surface for card templates, landing pages, webhooks, credential profiles, and template pairs
- `X-ACCT-ID` and `X-PAYLOAD-SIG`: auth headers for signed API requests

Do not rename these concepts in the host app abstractions unless the codebase already has a strong existing provider pattern.

## Mapping Document Shape

Use this structure if the host repo has no preferred format:

```md
# AccessGrid Entity Mapping

## Host Models
- Cardholder:
- Credential:
- Tenant/Site:

## Field Mapping
| Host field | AccessGrid field | Notes |
| --- | --- | --- |
| credential.id | metadata.pacs_credential_id | Stable dedupe key |

## Lifecycle Mapping
| Host state/event | AccessGrid action | Notes |
| --- | --- | --- |
| active | provision/resume | Depends on existing AG object |

## Persistence
- Where AG object IDs are stored
- Where dedupe keys are stored
- Where sync errors are stored
```

## Review Gate Before Coding

Do not start implementation until these are explicit:

- Where the AccessGrid client will live
- Which record stores the AccessGrid ID
- Which operation triggers provisioning
- Which operation or signal triggers suspend/resume/delete
- Which mechanism prevents duplicate issuance
- Which place exposes terminal failures to operators
