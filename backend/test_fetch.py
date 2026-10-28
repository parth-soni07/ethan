"""fetch_data with the BMRS client mocked out (no network)."""
import csv
from datetime import date

from backend import fetch_data as fd


def test_dedupes_and_keeps_only_january(tmp_path, monkeypatch):
    fuel_days = []

    def fake_stream(dataset, day, extra=""):
        if dataset == "WINDFOR":
            return [{"publishTime": "2026-01-01T08:00:00Z", "startTime": "2026-01-02T00:00:00Z", "generation": 9}]
        fuel_days.append(day)
        if day != date(2026, 1, 1):
            return []
        row = lambda start, pub, gen: {"startTime": start, "publishTime": pub, "generation": gen}
        return [
            row("2025-12-31T23:30:00Z", "2026-01-01T00:00:00Z", 1),  # before January: dropped
            row("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", 1),
            row("2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z", 2),  # latest revision wins
            row("2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z", 3),
            row("2026-02-01T00:00:00Z", "2026-02-01T00:30:00Z", 4),  # after January: dropped
        ]

    monkeypatch.setattr(fd, "stream", fake_stream)
    monkeypatch.setattr(fd, "DATA", tmp_path)
    fd.main()

    read = lambda name: list(csv.DictReader((tmp_path / name).read_text().splitlines()))
    assert read("actuals.csv") == [{"startTime": "2026-01-01T00:00:00Z", "generation": "2"}]
    assert len(read("forecasts.csv")) == 1  # same run returned for every day, kept once
    assert fuel_days[0] == fd.ACTUAL_FROM and fuel_days[-1] == fd.TO  # last publish day included
