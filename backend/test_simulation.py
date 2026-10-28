"""Simulation tests: a synthetic January with known truth, run through the real pipeline.

Truth is a 2-day sine wave of national wind. Forecast runs are published every 2 hours (like
WINDFOR) and cover the next 66 hours. Each forecast = truth + BIAS + noise whose spread grows
with lead time. Because the injected bias and noise are known, the recovered metrics can be
checked against the right answer, which the real data can't offer.
"""
import numpy as np
import pandas as pd
import pytest

from backend.analysis import accuracy, day_ahead
from backend.conftest import actuals, forecasts

BIAS, SIGMA_PER_HOUR, ACTUAL_NOISE, HORIZON_H = 800, 40, 100, 66
JAN = pd.date_range("2026-01-01", "2026-02-01", freq="30min", tz="UTC", inclusive="left")


def truth(t: pd.DatetimeIndex) -> np.ndarray:
    hours = (t - JAN[0]).total_seconds() / 3600
    return 10000 + 6000 * np.sin(2 * np.pi * hours / 48)


def simulate(rng, observed=lambda t, tr: tr):
    acts = actuals({"startTime": JAN, "generation": observed(JAN, truth(JAN)) + rng.normal(0, ACTUAL_NOISE, len(JAN))})
    rows = []
    for pub in pd.date_range("2025-12-29", "2026-01-31 22:00", freq="2h", tz="UTC"):
        starts = pd.date_range(pub + pd.Timedelta(hours=1), periods=HORIZON_H, freq="h")
        starts = starts[(starts >= JAN[0]) & (starts <= JAN[-1])]
        lead = (starts - pub).total_seconds() / 3600
        gen = truth(starts) + BIAS + rng.normal(0, SIGMA_PER_HOUR * lead)
        rows += zip([pub] * len(starts), starts, gen)
    return acts, forecasts(rows)


@pytest.fixture
def sim(use_data):
    acts, fcs = simulate(np.random.default_rng(7))
    use_data(acts, fcs)
    return acts, fcs


def test_selects_the_last_run_before_the_gate(sim):
    _, fcs = sim
    da = day_ahead(fcs, "09:00")
    # January is GMT; runs land on even hours, so the 08:00 D-1 run is the last one by 09:00.
    expected = da["startTime"].dt.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=8)
    assert len(da) == 744 and (da["publishTime"] == expected).all()


def test_recovers_injected_bias_and_noise_growth(sim):
    r = accuracy("09:00")
    assert r["overall"]["n"] == 744
    assert r["overall"]["bias"] == pytest.approx(BIAS, abs=150)
    rmse = [x["rmse"] for x in r["by_lead"]]
    assert rmse == sorted(rmse) and rmse[-1] > 2 * rmse[0]  # older forecasts miss more


def test_later_decision_time_means_smaller_error(sim):
    assert accuracy("11:00")["overall"]["rmse"] < accuracy("07:00")["overall"]["rmse"]


def test_p90_shortfall_matches_the_analytic_quantile(sim):
    _, fcs = sim
    lead = (lambda d: (d["startTime"] - d["publishTime"]).dt.total_seconds() / 3600)(day_ahead(fcs, "09:00"))
    rng = np.random.default_rng(1)
    sd = np.sqrt((SIGMA_PER_HOUR * lead.to_numpy()) ** 2 + ACTUAL_NOISE ** 2)
    draws = BIAS + rng.normal(0, 1, (400, len(sd))) * sd  # error = bias + forecast noise - actual noise
    assert accuracy("09:00")["overall"]["p90_shortfall"] == pytest.approx(np.quantile(draws, 0.9), rel=0.1)


def test_simulated_curtailment_shows_bias_growing_with_wind_level(use_data):
    """If output is capped by the grid while the forecast is not, over-forecast appears only at
    high wind: the pattern the real data shows, so the curtailment reading is at least consistent."""
    cap = 13000
    acts, fcs = simulate(np.random.default_rng(3), observed=lambda t, tr: np.minimum(tr, cap))
    fcs["generation"] -= BIAS  # unbiased forecast of uncapped wind
    use_data(acts, fcs)
    bias = {x["level"]: x["bias"] for x in accuracy("09:00")["by_level"]}
    assert abs(bias["5-10 GW"]) < 300
    assert bias["15-20 GW"] > bias["10-15 GW"] > bias["5-10 GW"]
    assert bias["15-20 GW"] > 2000
