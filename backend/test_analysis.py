import pandas as pd

from backend.analysis import day_ahead, join, metrics

T = lambda s: pd.Timestamp(s, tz="UTC")


def test_day_ahead_picks_latest_before_cutoff():
    fc = pd.DataFrame({
        "publishTime": [T("2026-01-14T06:30"), T("2026-01-14T08:30"), T("2026-01-14T10:30")],
        "startTime": [T("2026-01-15T12:00")] * 3,
        "generation": [100, 200, 300],
    })
    picked = day_ahead(fc, "09:00")
    assert picked["generation"].tolist() == [200]  # 10:30 is after the gate
    assert day_ahead(fc, "06:00").empty


def test_metrics_sign_and_shortfall():
    fc = pd.DataFrame({"startTime": [T("2026-01-15T00:00"), T("2026-01-15T01:00")],
                       "generation": [110, 90]})
    act = pd.DataFrame({"startTime": fc["startTime"], "generation": [100, 100]})
    m = metrics(join(fc, act))
    assert m["mae"] == 10 and m["bias"] == 0 and m["rmse"] == 10
    assert m["p90_shortfall"] > 0  # over-forecast hour means buying extra
