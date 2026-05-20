# Card Template Image Asset Requirements

Source: https://accessgrid.com/guides/knowledgebase/understanding-the-image-dimensions-necessary-for-google-and-apple-passes

Snapshot taken 2026-05-19. Re-fetch if AccessGrid changes asset specs.

Use these specs to validate logo / background / icon uploads on the host side **before** sending to AccessGrid. Rejecting early avoids round-trips and surfaces a clear error to the operator.

## Apple Wallet (DESFire)

| Asset | Sizes (px) | Notes |
|-------|------------|-------|
| Icon | 100×100, 200×200 | Used in push notifications |
| Background | 1536×969, 764×480, 512×323 | Fills the entire pass |
| Logo | h283×w≤1372, h140×w≤684, h74×w≤360 | Top-left of pass; width is a max, height is fixed per tier |

Accepted formats not enumerated in source — assume PNG and JPG; reject SVG.

## Google Wallet (HID)

| Asset | Sizes (px) | Format | Constraint |
|-------|------------|--------|------------|
| Logo | 200×200, 133×133, 67×67 | PNG | Must be square |
| Icon | 200×200, 133×133, 67×67 | PNG | Must be square |
| Background | up to 1456×928 | PNG | Any size within max |

## Google SmartTap

| Asset | Sizes (px) | Format | Max size |
|-------|------------|--------|----------|
| Logo | up to 430×430 | SVG, PNG, JPG | 10 MB; square preferred |
| Background | up to 1032×336 | PNG | Not specified |

## Host-side validation checklist

Add ORM-level (or model-level) validators on the `card_templates` table — once you reach the Complete integration level, the template owns logo / background / icon / colors.

For each uploaded asset:

1. Detect format (PNG / JPG / SVG) — reject if not allowed for the target platform.
2. Read dimensions — reject if outside the matrix above for the chosen `platform` column.
3. Enforce file-size cap (10 MB for SmartTap logo; pick a sensible global cap like 5 MB otherwise).
4. Reject SVG entirely for Apple Wallet and HID.
5. For "must be square" assets, enforce `width == height`.
6. Store the validated asset and surface dimension/format errors back to the operator before any AG API call.

## Color fields

`background_color`, `label_color`, `secondary_color` should be validated as 6- or 8-char hex (`#RRGGBB` or `#RRGGBBAA`). Strip leading `#` for transport if the SDK expects bare hex.
