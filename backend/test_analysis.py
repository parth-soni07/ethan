"""Unit and edge-case tests for day-ahead selection and metrics."""
import json
import math

import pandas as pd
import pytest

from backend import analysis
from backend.analysis import BIN, accuracy, day, day_ahead, join, metrics
from backend.conftest import actuals, forecasts

UK = "Europe/London"


def uk(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz=UK)


def picked(fc, cutoff):
    return day_ahead(fc, cutoff)["generation"].tolist()


# --- day_ahead: which forecast was available at the decision time --------------------------

def test_cutoff_is_inclusive_to_the_second():
    start = "2026-01-15T12:00Z"
    fc = forecasts([("2026-01-14T09:00:00Z", start, 1), ("2026-01-14T09:00:01Z", start, 2)])
    assert picked(fc, "09:00") == [1]


def test_latest_eligible_run_wins_per_start_time():
    s1, s2 = "2026-01-15T12:00Z", "2026-01-15T13:00Z"
    fc = forecasts([
        ("2026-01-13T20:00Z", s1, 1), ("2026-01-14T08:59Z", s1, 2),  # D-1 run beats D-2 run
        ("2026-01-13T20:00Z", s2, 3), ("2026-01-14T09:30Z", s2, 4),  # D-1 run is too late
    ])
    assert picked(fc, "09:00") == [2, 3]


def test_no_eligible_forecast_gives_empty_frame():
    fc = forecasts([("2026-01-14T10:30Z", "2026-01-15T12:00Z", 1)])
    assert day_ahead(fc, "09:00").empty


@pytest.mark.parametrize("cutoff", ["00:00", "23:59"])
def test_cutoff_extremes(cutoff):
    gate = uk(f"2026-01-14T{cutoff}").tz_convert("UTC")
    start = "2026-01-15T12:00Z"
    fc = forecasts([(gate, start, 1), (gate + pd.Timedelta(seconds=1), start, 2)])
    assert picked(fc, cutoff) == [1]


def test_delivery_day_is_the_uk_local_date():
    # 23:00Z on 30 June is 00:00 BST on 1 July, so its gate is 30 June 09:00 BST = 08:00Z.
    start = "2026-06-30T23:00Z"
    fc = forecasts([("2026-06-30T08:00:00Z", start, 1), ("2026-06-30T08:00:01Z", start, 2)])
    assert picked(fc, "09:00") == [1]


@pytest.mark.parametrize("delivery", ["2026-03-29", "2026-03-30", "2026-10-25", "2026-10-26"])
@pytest.mark.parametrize("cutoff", ["00:00", "00:30", "09:00", "23:59"])
def test_gate_is_wall_clock_across_clock_changes(delivery, cutoff):
    d_minus_1 = (pd.Timestamp(delivery) - pd.Timedelta(days=1)).date()
    gate = uk(f"{d_minus_1}T{cutoff}").tz_convert("UTC")
    start = uk(f"{delivery}T12:00").tz_convert("UTC")
    fc = forecasts([(gate, start, 1), (gate + pd.Timedelta(seconds=1), start, 2)])
    assert picked(fc, cutoff) == [1]


def test_selection_ignores_duplicate_index_labels():
    a = forecasts([("2026-01-14T08:00Z", "2026-01-15T12:00Z", 1)])
    b = forecasts([("2026-01-14T08:00Z", "2026-01-15T13:00Z", 2)])
    assert picked(pd.concat([a, b]), "09:00") == [1, 2]  # both frames have index 0


# --- join: hourly forecast vs half-hourly actuals ------------------------------------------

def test_join_matches_on_the_hour_and_drops_half_hours():
    fc = forecasts([("2026-01-14T08:00Z", "2026-01-15T00:00Z", 101)])
    act = actuals([("2026-01-15T00:00Z", 100), ("2026-01-15T00:30Z", 500)])
    assert join(fc, act)["error"].tolist() == [1]


def test_join_rejects_duplicate_actuals():
    fc = forecasts([("2026-01-14T08:00Z", "2026-01-15T00:00Z", 101)])
    act = actuals([("2026-01-15T00:00Z", 100), ("2026-01-15T00:00Z", 100)])
    with pytest.raises(pd.errors.MergeError):
        join(fc, act)


def test_load_dedupes_and_sorts_actuals(tmp_path, monkeypatch):
    (tmp_path / "actuals.csv").write_text(
        "startTime,generation\n2026-01-15T00:30:00Z,7\n2026-01-15T00:00:00Z,5\n2026-01-15T00:00:00Z,6\n")
    (tmp_path / "forecasts.csv").write_text("publishTime,startTime,generation\n")
    monkeypatch.setattr(analysis, "DATA", tmp_path)
    analysis.load.cache_clear()
    try:
        acts, _ = analysis.load()
        assert acts["generation"].tolist() == [6, 7]  # last duplicate kept, then time-ordered
    finally:
        analysis.load.cache_clear()


# --- metrics --------------------------------------------------------------------------------

def joined(fc_values, act_values):
    starts = pd.date_range("2026-01-15", periods=len(fc_values), freq="h", tz="UTC")
    return join(forecasts([("2026-01-14T08:00Z", s, f) for s, f in zip(starts, fc_values)]),
                actuals(list(zip(starts, act_values))))


def test_metrics_hand_computed():
    m = metrics(joined([110, 80, 130, 100, 100], [100, 100, 100, 100, 50]))  # errors 10,-20,30,0,50
    assert m == pytest.approx({"n": 5, "mae": 22, "rmse": math.sqrt(780), "bias": 14, "mape": 32, "actual_mean": 90,
                               "p90_shortfall": 42})


def test_all_under_forecast_needs_no_backup():
    m = metrics(joined([90, 80], [100, 100]))
    assert m["bias"] == -15 and m["p90_shortfall"] == 0


def test_single_row():
    m = metrics(joined([120], [100]))
    assert m == pytest.approx({"n": 1, "mae": 20, "rmse": 20, "bias": 20, "mape": 20, "p90_shortfall": 20,
                               "actual_mean": 100})


def test_zero_actual_is_excluded_from_mape_and_json_safe():
    m = metrics(joined([10, 10], [0, 10]))
    assert m["mape"] == 0
    json.dumps(m, allow_nan=False)
    assert metrics(joined([10], [0]))["mape"] is None


# --- accuracy breakdowns (synthetic) ---------------------------------------------------------

def test_breakdowns_on_a_synthetic_day(use_data):
    starts = pd.date_range("2026-01-15", periods=24, freq="h", tz="UTC")
    use_data(
        actuals([(s, 18000) for s in starts]),
        forecasts([("2026-01-14T08:00Z", s, 21000) for s in starts]  # day-ahead run
                  + [(s, s, 18000) for s in starts]  # lead exactly 0: in 0-6h, never day-ahead
                  + [(s + pd.Timedelta(hours=1), s, 0) for s in starts]),  # negative lead: excluded
    )
    r = accuracy("09:00")
    assert r["overall"]["n"] == 24 and r["overall"]["bias"] == 3000
    assert [x["level"] for x in r["by_level"]] == ["20+ GW"]
    assert sum(x["n"] for x in r["by_lead"]) == 48
    assert next(x for x in r["by_lead"] if x["lead"] == "0-6h")["n"] == 24
    assert r["histogram"] == [{"from": 3000, "to": 4000, "count": 24}]


def test_histogram_bins_are_contiguous_and_cover_every_hour():
    r = accuracy("09:00")
    bins = r["histogram"]
    assert all(b["from"] % BIN == 0 and b["to"] - b["from"] == BIN for b in bins)
    assert all(a["to"] == b["from"] for a, b in zip(bins, bins[1:]))
    assert sum(b["count"] for b in bins) == r["overall"]["n"]


def test_accuracy_is_cached_per_cutoff():
    assert accuracy("09:00") is accuracy("09:00")


# --- real-data golden values: keep the README finding honest ---------------------------------

def test_real_data_breakdowns_and_readme_figures():
    r = accuracy("09:00")
    o = r["overall"]
    assert o["n"] == 31 * 24
    for key in ("by_day", "by_hour", "by_level"):
        assert sum(x["n"] for x in r[key]) == o["n"], key
    assert (round(o["bias"]), round(o["mae"]), round(o["p90_shortfall"])) == (1852, 2127, 4306)
    assert r["by_lead"][0]["lead"] == "0-6h" and round(r["by_lead"][0]["bias"]) == 1548
    assert r["by_level"][-1]["level"] == "20+ GW" and round(r["by_level"][-1]["bias"]) == 4543


@pytest.mark.parametrize("cutoff", ["00:00", "07:00", "09:00", "10:00", "11:00", "23:59"])
def test_real_data_is_json_safe_at_every_cutoff(cutoff):
    json.dumps(accuracy(cutoff), allow_nan=False)


def test_date_range_matches_the_data():
    assert analysis.date_range() == ("2026-01-01", "2026-01-31")


# --- day -------------------------------------------------------------------------------------

def test_day_on_real_data():
    d = day("2026-01-15")
    times = [p["startTime"] for p in d["points"]]
    assert len(times) == 48 and times == sorted(times)
    with_fc = [p for p in d["points"] if p["forecast"] is not None]
    assert len(with_fc) == 24 and all(p["startTime"][14:16] == "00" for p in with_fc)
    assert d["metrics"]["n"] == 24
    json.dumps(d, allow_nan=False)


def test_day_without_forecasts_has_null_metrics_and_sorted_points(use_data):
    starts = pd.date_range("2026-01-15", periods=48, freq="30min", tz="UTC")
    use_data(actuals([(s, 1) for s in starts]).sample(frac=1, random_state=0), forecasts())
    d = day("2026-01-15")
    assert d["metrics"] is None
    assert [p["startTime"] for p in d["points"]] == [s.isoformat() for s in starts]


@pytest.mark.parametrize("date, points", [("2026-03-29", 46), ("2026-10-25", 50), ("2026-06-15", 48)])
def test_day_window_follows_uk_local_midnight(use_data, date, points):
    starts = pd.date_range("2026-03-27", "2026-10-28", freq="30min", tz="UTC")
    use_data(actuals([(s, 1) for s in starts]), forecasts())
    d = day(date)
    assert len(d["points"]) == points
    assert {pd.Timestamp(p["startTime"]).tz_convert(UK).date().isoformat() for p in d["points"]} == {date}
