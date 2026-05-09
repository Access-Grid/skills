#!/usr/bin/env python3

import sys


TEMPLATE = """# AccessGrid Entity Mapping: {system_name}

## Summary

- Host system:
- Deployment model: cloud | on-prem
- Integration depth: simple | comprehensive | deep
- Sync direction: PACS->AG only | bidirectional

## Host Models

- Cardholder/User:
- Credential/Badge/Card:
- Tenant/Site/Building:
- Sync attempt or event log:

## AccessGrid Configuration

- Account ID source:
- Secret key source:
- Template strategy:
- Landing page strategy:
- Delivery owner: AG-managed | host-app `install_url`

## Field Mapping

| Host field | AccessGrid field | Required | Notes |
| --- | --- | --- | --- |
| credential.id | metadata.pacs_credential_id | yes | Stable identifier for dedupe and reconciliation |
| user.full_name | full_name | yes | |
| credential.site_code | credential.site_code | maybe | Use when host stores Wiegand-style data |
| credential.card_number | credential.card_number | maybe | |
| credential.file_data | credential.file_data | maybe | Use when host stores raw credential bytes |

## Lifecycle Mapping

| Host state/event | AccessGrid action | Preconditions | Notes |
| --- | --- | --- | --- |
| active without AG ID | provision | No linked AG object yet | |
| active with AG ID | resume or noop | AG object exists | |
| suspended | suspend | AG object exists | |
| deleted/revoked | delete | AG object exists | |

## Persistence

- Where AccessGrid card/pass ID is stored:
- Where dedupe key or sync-attempt state is stored:
- Where terminal sync errors are stored:
- Where webhook event IDs or checkpoints are stored:

## Observability

- Structured log fields:
- Correlation ID path:
- Operator-visible failure path:

## Open Questions

- 
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: scaffold_mapping_doc.py <system-name>", file=sys.stderr)
        return 1

    system_name = sys.argv[1].strip()
    if not system_name:
        print("system-name must not be empty", file=sys.stderr)
        return 1

    print(TEMPLATE.format(system_name=system_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
