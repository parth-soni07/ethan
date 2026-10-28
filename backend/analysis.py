"""Day-ahead forecast selection and accuracy metrics. Pure functions over DataFrames."""
from functools import cache, lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
UK = "Europe/London"
DEFAULT_CUTOFF = "09:00"  # just before the 09:20 GB day-ahead auction gate
LEAD_BUCKETS = [0, 6, 12, 24, 36, 48, 72]
LEVEL_BANDS = [0, 5000, 10000, 15000, 20000, np.inf]
LEVEL_LABELS = ["0-5 GW", "5-10 GW", "10-15 GW", "15-20 GW", "20+ GW"]
BIN = 1000  # histogram bin width, MW


@cache
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    actuals = pd.read_csv(DATA / "actuals.csv", parse_dates=["startTime"])
    forecasts = pd.read_csv(DATA / "forecasts.csv", parse_dates=["publishTime", "startTime"])
    # One actual per settlement period; join() relies on it.
    actuals = actuals.drop_duplicates("startTime", keep="last").sort_values("startTime", ignore_index=True)
    return actuals, forecasts


def date_range() -> tuple[str, str]:
    """First and last UK delivery day covered by the actuals."""
    days = load()[0]["startTime"].dt.tz_convert(UK).dt.strftime("%Y-%m-%d")
    return days.min(), days.max()


def day_ahead(forecasts: pd.DataFrame, cutoff: str = DEFAULT_CUTOFF) -> pd.DataFrame:
    """Per startTime, the latest forecast published at or before `cutoff` UK wall-clock time on
    D-1, where D is the UK delivery day of that startTime."""
    # Gate on the wall clock, then localise: adding hours to a tz-aware midnight is off by one
    # hour when D-1 is a clock-change day.
    wall = forecasts["startTime"].dt.tz_convert(UK).dt.tz_localize(None).dt.normalize()
    gate = (wall - pd.Timedelta(days=1) + pd.Timedelta(f"{cutoff}:00")).dt.tz_localize(
        UK, ambiguous=True, nonexistent="shift_forward")
    eligible = forecasts[forecasts["publishTime"] <= gate.dt.tz_convert("UTC")]
    return (eligible.sort_values(["startTime", "publishTime"])
            .drop_duplicates("startTime", keep="last").reset_index(drop=True))


def join(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    # WINDFOR is hourly, FUELHH half-hourly: compare on the forecast's hourly startTime.
    df = forecasts.merge(actuals, on="startTime", suffixes=("_fc", "_act"), validate="many_to_one")
    df = df.rename(columns={"generation_fc": "forecast", "generation_act": "actual"})
    df["error"] = df["forecast"] - df["actual"]  # > 0: over-forecast -> shortfall to buy
    return df


def metrics(df: pd.DataFrame) -> dict:
    e = df["error"]
    positive = df["actual"] > 0  # MAPE is undefined at zero output
    return {
        "n": int(len(df)),
        "mae": float(e.abs().mean()),
        "rmse": float(np.sqrt((e ** 2).mean())),
        "bias": float(e.mean()),
        "mape": float((e[positive].abs() / df.loc[positive, "actual"]).mean() * 100) if positive.any() else None,
        # MW of extra procurement that would have covered the shortfall in 90% of hours.
        "p90_shortfall": float(max(e.quantile(0.9), 0)),
    }


@lru_cache(maxsize=64)  # data is static; warm serverless instances reuse results per cutoff
def accuracy(cutoff: str = DEFAULT_CUTOFF) -> dict:
    actuals, forecasts = load()
    da = join(day_ahead(forecasts, cutoff), actuals)
    local = da["startTime"].dt.tz_convert(UK)
    da["hour"], da["day"] = local.dt.hour, local.dt.strftime("%Y-%m-%d")
    da["level"] = pd.cut(da["forecast"], LEVEL_BANDS, labels=LEVEL_LABELS, right=False)
    allf = join(forecasts, actuals)
    allf["lead_h"] = (allf["startTime"] - allf["publishTime"]).dt.total_seconds() / 3600
    allf = allf[allf["lead_h"] >= 0]
    allf["lead"] = pd.cut(allf["lead_h"], LEAD_BUCKETS, right=False)
    lo, hi = np.floor(da["error"].min() / BIN) * BIN, np.ceil(da["error"].max() / BIN) * BIN
    counts, edges = np.histogram(da["error"], bins=np.arange(lo, max(hi, lo + BIN) + 1, BIN))
    return {
        "cutoff": cutoff,
        "overall": metrics(da),
        "by_day": [{"day": d, **metrics(g)} for d, g in da.groupby("day")],
        "by_hour": [{"hour": h, **metrics(g)} for h, g in da.groupby("hour")],
        "by_lead": [{"lead": f"{iv.left}-{iv.right}h", **metrics(g)}
                    for iv, g in allf.groupby("lead", observed=True)],
        # Over-forecast that grows with wind level is consistent with curtailment (metered output
        # constrained off when the grid can't take it). A hypothesis; see README.
        "by_level": [{"level": lvl, **metrics(g)}
                     for lvl, g in da.groupby("level", observed=True)],
        "histogram": [{"from": int(a), "to": int(b), "count": int(c)}
                      for a, b, c in zip(edges[:-1], edges[1:], counts)],
    }


def day(date: str, cutoff: str = DEFAULT_CUTOFF) -> dict:
    actuals, forecasts = load()
    # Local midnight to local midnight: 23 or 25 hours on clock-change days.
    start, end = (pd.Timestamp(d).tz_localize(UK) for d in (date, pd.Timestamp(date) + pd.Timedelta(days=1)))
    window = lambda df: df[(df["startTime"] >= start) & (df["startTime"] < end)]
    da, act = window(day_ahead(forecasts, cutoff)), window(actuals)
    joined = join(da, act)
    out = act.merge(da, on="startTime", how="left", suffixes=("_act", "_fc")).sort_values("startTime")
    return {
        "date": date,
        "metrics": metrics(joined) if len(joined) else None,
        "points": [{"startTime": r.startTime.isoformat(),
                    "actual": r.generation_act,
                    "forecast": None if pd.isna(r.generation_fc) else r.generation_fc,
                    "publishTime": None if pd.isna(r.publishTime) else r.publishTime.isoformat()}
                   for r in out.itertuples()],
    }
