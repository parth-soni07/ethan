import pandas as pd
import pytest

from backend import analysis


def frame(rows, columns):
    """DataFrame with every *Time column parsed as UTC, like load() produces."""
    df = pd.DataFrame(rows, columns=columns)
    for c in columns:
        if c.endswith("Time"):
            df[c] = pd.to_datetime(df[c], utc=True)
    return df


def forecasts(rows=()):
    return frame(rows, ["publishTime", "startTime", "generation"])


def actuals(rows=()):
    return frame(rows, ["startTime", "generation"])


CACHES = (analysis.accuracy, analysis._day_ahead_for, analysis.date_range)


@pytest.fixture(autouse=True)
def fresh_caches():
    for c in CACHES:
        c.cache_clear()
    yield
    for c in CACHES:
        c.cache_clear()


@pytest.fixture
def use_data(monkeypatch):
    """Point analysis.load() at in-memory frames instead of the committed CSVs."""
    def use(acts: pd.DataFrame, fcs: pd.DataFrame) -> None:
        monkeypatch.setattr(analysis, "load", lambda: (acts, fcs))
    return use
