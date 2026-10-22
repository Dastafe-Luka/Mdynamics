#!/usr/bin/env python3
"""Update the rates embedded in index.html from the National Bank of Georgia API.

Reads the JSON block <script id="nbg-data">, fetches every day from one week
before the last stored rate up to tomorrow (the bank publishes tomorrow's
rate at about 17:00 Tbilisi time), and writes the block back.
Standard library only, so it runs on a bare GitHub Actions runner.
"""
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = ("https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"
       "?currencies=USD&currencies=EUR&date={}")
BLOCK = re.compile(r'(<script id="nbg-data" type="application/json">)(.*?)(</script>)', re.S)
RECHECK_DAYS = 7  # re-read the last week in case a rate was corrected


def fetch(day):
    """Return (valid_from, usd, eur) for the rate in force on `day`."""
    url = API.format(day.isoformat())
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lari-pulse/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            cur = {c["code"]: c for c in data[0]["currencies"]}
            usd, eur = cur["USD"], cur["EUR"]
            if usd["quantity"] != 1 or eur["quantity"] != 1:
                raise ValueError("unexpected quantity")
            return usd["validFromDate"][:10], round(float(usd["rate"]), 4), round(float(eur["rate"]), 4)
        except Exception as exc:  # network hiccup or bad payload: retry, then give up
            if attempt == 3:
                raise RuntimeError(f"{day}: {exc}") from exc
            time.sleep(3 * (attempt + 1))


def main(path):
    html = open(path, encoding="utf-8").read()
    m = BLOCK.search(html)
    if not m:
        sys.exit("data block <script id=\"nbg-data\"> not found")
    rows = {r[0]: [r[0], r[1], r[2]] for r in json.loads(m.group(2))}
    last = date.fromisoformat(max(rows))
    tomorrow = (datetime.now(timezone.utc) + timedelta(hours=4)).date() + timedelta(days=1)

    changed, errors, ok = 0, [], 0
    day = last - timedelta(days=RECHECK_DAYS)
    while day <= tomorrow:
        try:
            valid, usd, eur = fetch(day)
            ok += 1
            if valid <= tomorrow.isoformat() and rows.get(valid) != [valid, usd, eur]:
                rows[valid] = [valid, usd, eur]
                changed += 1
        except RuntimeError as exc:
            errors.append(str(exc))
        day += timedelta(days=1)
        time.sleep(0.2)

    for e in errors:
        print("warning:", e)
    if errors and not ok:
        sys.exit("NBG API unreachable; nothing updated")
    if not changed:
        print("no new rates; last:", max(rows))
        return
    data = json.dumps([rows[k] for k in sorted(rows)], separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html[:m.start(2)] + data + html[m.end(2):])
    print(f"updated {changed} row(s); last: {max(rows)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "index.html")
