"""One-off pull of Elexon BMRS data for January 2026 day-ahead decisions into data/*.csv.

Run: python -m backend.fetch_data
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen

BASE = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
DATA = Path(__file__).resolve().parent.parent / "data"

# Delivery days are Jan 1-31; their day-ahead forecasts are published from late December.
FORECAST_FROM, ACTUAL_FROM, TO = date(2025, 12, 29), date(2026, 1, 1), date(2026, 2, 1)


def stream(dataset: str, day: date, extra: str = "") -> list[dict]:
    url = (f"{BASE}/{dataset}/stream?publishDateTimeFrom={day}T00:00:00Z"
           f"&publishDateTimeTo={day + timedelta(days=1)}T00:00:00Z{extra}")
    with urlopen(url, timeout=60) as r:
        return json.load(r)


def days(start: date, end: date):
    while start < end:
        yield start
        start += timedelta(days=1)


def write(name: str, rows: list[dict], fields: list[str]) -> None:
    with open(DATA / name, "w", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


def main() -> None:
    DATA.mkdir(exist_ok=True)
    # Publish windows are half-open per day, but dedupe anyway in case the API is inclusive.
    forecasts = {(r["publishTime"], r["startTime"]): r
                 for d in days(FORECAST_FROM, TO) for r in stream("WINDFOR", d)}
    # FUELHH can be republished; keep the latest publish per settlement period.
    actuals: dict[str, dict] = {}
    for d in days(ACTUAL_FROM, TO + timedelta(days=1)):
        for r in stream("FUELHH", d, "&fuelType=WIND"):
            if r["startTime"] >= f"{TO}" or r["startTime"] < f"{ACTUAL_FROM}":
                continue
            if r["startTime"] not in actuals or r["publishTime"] > actuals[r["startTime"]]["publishTime"]:
                actuals[r["startTime"]] = r
    write("forecasts.csv", sorted(forecasts.values(), key=lambda r: (r["publishTime"], r["startTime"])),
          ["publishTime", "startTime", "generation"])
    write("actuals.csv", sorted(actuals.values(), key=lambda r: r["startTime"]),
          ["startTime", "generation"])


if __name__ == "__main__":
    main()
