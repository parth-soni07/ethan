# UK wind day-ahead forecast accuracy

Shows the latest national wind forecast (Elexon BMRS `WINDFOR`) a buyer had at the day-ahead decision
point, against actual wind generation (`FUELHH`, fuelType `WIND`). It also measures how wrong those
forecasts were across January 2026.

**Live app:** _TODO: Vercel URL_

## AI tools disclosure

AI tools were used to build this project. Claude Code (Anthropic) helped with scaffolding, code,
tests and documentation. I reviewed, ran and verified all output, and I own the design decisions
and the analysis.

## Key definitions

- **Latest forecast available**: for each delivery day D (UK local), take the `WINDFOR` run with the
  greatest `publishTime` at or before **D-1 09:00 UK**. That is just before the 09:20 GB day-ahead
  auction gate. You can change the cutoff with the `cutoff` query parameter or in the UI.
- **Error** = forecast − actual (MW). A positive error is an over-forecast, i.e. a shortfall the
  buyer must cover with extra (thermal) power.
- **P90 shortfall**: the 90th percentile of error. Buying this many MW of extra power would have
  covered the shortfall in 90% of hours.
- `WINDFOR` is hourly and `FUELHH` is half-hourly, so they are compared at hourly `startTime`s.

## Finding: the forecast runs high, most of all when it is windy

All figures are at the default 09:00 cutoff (`backend/test_analysis.py` pins them to the data).
Day-ahead forecasts over-forecast delivered wind by about 1.9 GW on average. Forecasts made 0-6
hours ahead are still about 1.5 GW high, so it is not only a lead-time effect. The gap is largest at
high wind: +4.5 GW when 20 GW or more is forecast, against +0.6 GW below 5 GW (a small band: 30
hours). That is consistent with curtailment, where wind farms are paid to turn down when the grid
can't take their output, so metered `FUELHH` output falls below the unconstrained `WINDFOR`
forecast. It is a hypothesis: confirming it needs balancing-action data, which is outside this
brief's Elexon wind-only scope. A simulation test (`test_simulated_curtailment_shows_bias_growing_with_wind_level`)
shows that capped output produces exactly this pattern.

## Layout

| Path | What |
|---|---|
| `backend/fetch_data.py` | One-off pull of the January 2026 window from BMRS into `data/*.csv` |
| `backend/analysis.py` | Day-ahead forecast selection + MAE/RMSE/bias/MAPE/P90, by day, hour, lead time and forecast level, plus an error histogram |
| `backend/app.py` | FastAPI: `GET /api/day?date=&cutoff=`, `GET /api/accuracy?cutoff=`; also serves the built UI |
| `backend/test_analysis.py` | Unit and edge-case tests: cutoff boundaries, UK clock changes, joins, metrics, real-data golden values |
| `backend/test_simulation.py` | Simulation tests: a synthetic month with known bias and noise, checked against the right answer |
| `backend/test_api.py` | HTTP contract, input validation (422s) and security headers |
| `backend/test_fetch.py` | `fetch_data` dedupe and date windows with BMRS mocked out |
| `api/index.py` | Vercel Python entrypoint |
| `frontend/` | Next.js (App Router, static export) + Recharts UI; claymorphism surfaces on an Apple system palette |
| `data/` | Committed BMRS snapshot (the data is historical, so it is not fetched live) |

## Run

```bash
# Docker (API + UI on :8000)
docker build -t wind . && docker run -p 8000:8000 wind

# Local dev (Python 3.12: pandas 2.2 has no wheels for 3.13+)
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn backend.app:app --reload        # API on :8000
cd frontend && npm install && npm run dev          # UI on :3000, proxies /api to :8000

# Tests (warnings are errors; config in pytest.ini) / refresh data
.venv/bin/pytest -q
.venv/bin/python -m backend.fetch_data
```

## Deploy

`vercel deploy`. `vercel.json` builds the Next.js UI as a static export (`frontend/out`) and runs `api/index.py` as a Python
function. The Dockerfile is for local and container hosting (it runs on Heroku's container stack as-is).
