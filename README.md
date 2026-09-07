# SportsSpace Twin Cities MVP

## Purpose
Test one question before building a marketplace:

> Will hockey coaches/team managers repeatedly prefer one normalized search over checking multiple rink websites and sale feeds?

## What this prototype does
- Filters captured Twin Cities ice inventory by date, time, price, city, and full-sheet status.
- Links every result back to its original public source.
- Shows the integration pipeline (ingested / readable / blocked).
- Includes a local-only "save alert" interaction to test whether alerts are compelling.

## What this prototype intentionally does NOT do
- Payments or booking
- User accounts
- Automated email/SMS
- Scraping every facility
- Turf/court inventory
- Claims of real-time completeness

## Data status
Snapshot created September 7, 2026.

Seed inventory is from Rinkfinder public Ice For Sale listings, plus research on direct facility schedule sources:
- https://rinkfinder.com/ice-for-sale/
- https://www.plymouthmn.gov/departments/parks-recreation-/ice-center/rentals-rates
- https://mnplymouthweb.myvscloud.com/webtrac/web/search.html?FRClass=Ice%20Arena&module=FR
- https://www.richfieldmn.gov/icearena

Before any rental decision, verify the source directly because availability can change.

## 5-minute tester script
1. "Pretend you need a sheet this week. Find something you could use."
2. "How would you have searched for that ice without this page?"
3. "What information is missing before you'd contact/book?"
4. "Would you save an alert for a preferred area/time/price?"
5. "Would you come back to this site next time? Why or why not?"

Do not ask "Do you like the idea?" until after the person has tried to use it.

## Continue criteria for the next 7 days
Proceed if:
- 5+ target users actually test the page,
- at least 3 say they would use it again,
- at least 2 want alerts,
- and at least one rink manager is open to a feed/listing relationship.

## Next technical milestone
Build a repeatable Plymouth WebTrac ingestion workflow, then add a second facility-native schedule source.

## Plymouth direct-ingestion proof

`plymouth_ingest.py` is the first facility-native parser.

What it does:
- Opens Plymouth's public WebTrac/MyVSCloud Ice Arena search.
- Drives the visible date form rather than relying on a brittle CSRF URL.
- Reads Rink A/B/C availability.
- Ignores blocks explicitly marked `Unavailable`.
- Merges adjacent 15-minute open blocks into useful windows.
- Defaults to windows of 60+ minutes.
- Emits normalized JSON ready to merge with SportsSpace inventory.
- Does **not** guess the prime/non-prime rate when Plymouth's published page
  does not expose the clock-time classification.

### Live run

```bash
pip install -r requirements.txt
playwright install chromium
python plymouth_ingest.py --date 2026-09-14 --min-minutes 60 --out plymouth.json
```

### Offline parser test

```bash
python test_plymouth_parser.py
```

The included Aug. 29 fixture is based on the public Plymouth schedule structure
and proves that adjacent 15-minute slots merge correctly into longer windows.

### Known deployment requirement

The current ChatGPT code runtime used to assemble this prototype does not have
general outbound internet access, so the Playwright live fetch cannot be
end-to-end executed here. The parsing layer is unit-tested locally; the live
browser step should be run from a normal networked host (GitHub Actions,
Render, Railway, Fly.io, a VPS, etc.) before production use.
