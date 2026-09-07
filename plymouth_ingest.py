#!/usr/bin/env python3
"""
SportsSpace Plymouth Ice Center ingestion prototype.

Live mode:
    python plymouth_ingest.py --date 2026-09-14 --min-minutes 60 --out plymouth.json

Fixture mode (no internet/browser required):
    python plymouth_ingest.py --date 2026-08-29 --from-text fixtures/plymouth_2026-08-29.txt

Why Playwright?
Plymouth's WebTrac/MyVSCloud facility search keeps the selected date in a
session/form workflow rather than in a simple stable date query parameter.
This script drives the public "Date You Are Looking For" + "Search Date"
controls, then normalizes the visible availability into SportsSpace records.

This is a proof-of-concept. It does not reserve ice and does not bypass
authentication or access controls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, date as Date, time as Time, timedelta
from pathlib import Path
from typing import Iterable

BASE_URL = (
    "https://mnplymouthweb.myvscloud.com/webtrac/web/search.html"
    "?FRClass=Ice%20Arena&module=FR"
)
SOURCE_PAGE = "https://www.plymouthmn.gov/departments/parks-recreation-/ice-center/rentals-rates"
FACILITY = "Plymouth Ice Center"
CITY = "Plymouth"
PHONE = "763-509-5250"

RINK_RE = re.compile(r"(?m)^\s*Rink\s+([ABC])\s*$")
TIME_RE = re.compile(
    r"(?i)(\d{1,2}:\d{2}\s*(?:am|pm))\s*-\s*"
    r"(\d{1,2}:\d{2}\s*(?:am|pm))\s*(Unavailable)?"
)

@dataclass
class Window:
    facility: str
    sheet: str
    city: str
    date: str
    start: str
    end: str
    duration_minutes: int
    price: None
    price_note: str
    booking_method: str
    booking_phone: str
    source: str
    source_url: str
    captured_at: str

def _to_minutes(value: str) -> int:
    t = datetime.strptime(re.sub(r"\s+", " ", value.strip()).upper(), "%I:%M %p")
    return t.hour * 60 + t.minute

def _hhmm(minutes: int) -> str:
    # Allow midnight represented as 1440.
    if minutes == 1440:
        return "24:00"
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

def _normalize_end(start_min: int, end_min: int) -> int:
    # 11:45 PM -> 12:00 AM should be treated as 1440, not 0.
    if end_min <= start_min:
        return end_min + 24 * 60
    return end_min

def split_rink_sections(body_text: str) -> dict[str, str]:
    matches = list(RINK_RE.finditer(body_text))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body_text)
        sections[f"Rink {match.group(1)}"] = body_text[start:end]
    return sections

def parse_open_intervals(section: str) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for m in TIME_RE.finditer(section):
        start = _to_minutes(m.group(1))
        end = _normalize_end(start, _to_minutes(m.group(2)))
        unavailable = bool(m.group(3))
        if not unavailable:
            intervals.append((start, end))
    return intervals

def merge_adjacent(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted(intervals)
    if not ordered:
        return []
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        prev = merged[-1]
        if start <= prev[1]:  # adjacent or overlapping
            prev[1] = max(prev[1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]

def published_rate_note(search_date: Date) -> str:
    # Plymouth publishes tier amounts but the public page does not state the
    # exact prime/non-prime clock boundaries in the text we can reliably ingest.
    # We intentionally do NOT guess which tier applies.
    if search_date.month in (4, 5, 6, 7, 8):
        return "Published 2026 Apr–Aug rate: $240/hr + tax; call Plymouth to confirm."
    return (
        "Published 2026 Jan–Mar / Sep–Dec tiers: $275 prime, $200 non-prime, "
        "$160 early weekday + tax; exact tier not inferred—call Plymouth to confirm."
    )

def normalize(body_text: str, search_date: Date, min_minutes: int = 60) -> list[Window]:
    captured = datetime.now().astimezone().isoformat(timespec="seconds")
    records: list[Window] = []
    sections = split_rink_sections(body_text)

    if not sections:
        raise ValueError("Could not find Rink A/B/C sections in the page text.")

    for rink, section in sections.items():
        merged = merge_adjacent(parse_open_intervals(section))
        for start, end in merged:
            duration = end - start
            if duration < min_minutes:
                continue
            records.append(
                Window(
                    facility=FACILITY,
                    sheet=rink,
                    city=CITY,
                    date=search_date.isoformat(),
                    start=_hhmm(start),
                    end=_hhmm(end),
                    duration_minutes=duration,
                    price=None,
                    price_note=published_rate_note(search_date),
                    booking_method="Call to reserve",
                    booking_phone=PHONE,
                    source="Plymouth WebTrac / MyVSCloud",
                    source_url=BASE_URL,
                    captured_at=captured,
                )
            )
    return records

async def _fill_date_input(page, date_string: str) -> None:
    """
    Find and fill WebTrac's "Date You Are Looking For" control.

    WebTrac often keeps Search Filters collapsed on the result view, so the
    date input can exist but not be visible until that panel is expanded.
    """
    target_text = datetime.strptime(date_string, "%Y-%m-%d").strftime("%m/%d/%Y")

    async def try_fill() -> bool:
        # 1) Best case: accessible label is wired correctly.
        try:
            loc = page.get_by_label("Date You Are Looking For", exact=False)
            if await loc.count():
                el = loc.first
                typ = (await el.get_attribute("type") or "").lower()
                await el.fill(date_string if typ == "date" else target_text)
                return True
        except Exception:
            pass

        # 2) Common date-like inputs.
        selectors = [
            'input[type="date"]:visible',
            'input[name*="date" i]:visible',
            'input[id*="date" i]:visible',
            'input[placeholder*="date" i]:visible',
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if await loc.count():
                    el = loc.first
                    typ = (await el.get_attribute("type") or "").lower()
                    await el.fill(date_string if typ == "date" else target_text)
                    return True
            except Exception:
                pass

        # 3) Inspect nearby visible text.
        inputs = page.locator("input:visible")
        count = await inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            try:
                nearby = await el.evaluate(
                    """el => {
                        let n = el;
                        for (let i=0; i<6 && n; i++, n=n.parentElement) {
                          const t = (n.innerText || '').trim();
                          if (t.includes('Date You Are Looking For')) return t;
                        }
                        return '';
                    }"""
                )
                if "Date You Are Looking For" in nearby:
                    typ = (await el.get_attribute("type") or "").lower()
                    await el.fill(date_string if typ == "date" else target_text)
                    return True
            except Exception:
                continue
        return False

    # Try the currently visible page first.
    if await try_fill():
        return

    # WebTrac commonly collapses Search Filters on result pages.
    for locator in (
        page.get_by_role("button", name=re.compile(r"Search Filters", re.I)),
        page.get_by_text(re.compile(r"Search Filters", re.I)),
    ):
        try:
            if await locator.count():
                await locator.first.click()
                await page.wait_for_timeout(500)
                if await try_fill():
                    return
        except Exception:
            pass

    # Emit useful diagnostics into the GitHub Actions log if WebTrac changes.
    try:
        print("DEBUG current URL:", page.url)
        print("DEBUG page title:", await page.title())
        inputs = page.locator("input")
        print("DEBUG total inputs:", await inputs.count())
        for i in range(min(await inputs.count(), 25)):
            el = inputs.nth(i)
            print(
                "DEBUG input",
                i,
                "type=", await el.get_attribute("type"),
                "name=", await el.get_attribute("name"),
                "id=", await el.get_attribute("id"),
                "placeholder=", await el.get_attribute("placeholder"),
                "visible=", await el.is_visible(),
            )
    except Exception:
        pass

    raise RuntimeError("Could not locate the Plymouth date search input.")


async def fetch_live_body(search_date: str, timeout_ms: int = 45000) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Live mode requires Playwright. Run: pip install playwright && "
            "playwright install chromium"
        ) from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(timeout_ms)

        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await _fill_date_input(page, search_date)

        button = page.get_by_role("button", name=re.compile(r"Search Date", re.I))
        if not await button.count():
            button = page.get_by_text(re.compile(r"Search Date", re.I))
        await button.first.click()

        # WebTrac may refresh in-place or navigate; wait for the rink sections.
        await page.get_by_text("Rink A", exact=True).wait_for()
        await page.wait_for_timeout(800)
        body = await page.locator("body").inner_text()
        await browser.close()
        return body

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--min-minutes", type=int, default=60)
    ap.add_argument("--from-text", type=Path, help="Parse a saved page-text fixture")
    ap.add_argument("--save-raw", type=Path, help="Save live body text for debugging")
    ap.add_argument("--out", type=Path, help="Output JSON path; otherwise stdout")
    args = ap.parse_args()

    search_date = Date.fromisoformat(args.date)

    if args.from_text:
        body = args.from_text.read_text(encoding="utf-8")
    else:
        body = asyncio.run(fetch_live_body(args.date))
        if args.save_raw:
            args.save_raw.write_text(body, encoding="utf-8")

    records = [asdict(x) for x in normalize(body, search_date, args.min_minutes)]
    payload = {
        "source": "Plymouth Ice Center",
        "searched_date": args.date,
        "minimum_window_minutes": args.min_minutes,
        "record_count": len(records),
        "records": records,
    }
    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {len(records)} records to {args.out}")
    else:
        print(text)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
