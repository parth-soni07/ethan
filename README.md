# ethan: UK wind day-ahead forecast API

The backend of a pilot portal for a UK energy buyer. For each delivery day it returns the latest
national wind forecast (Elexon BMRS `WINDFOR`) that was available at the day-ahead decision time, set
against actual wind generation (`FUELHH`, fuelType `WIND`), and measures how wrong those forecasts
were across January 2026.

The UI lives in a separate repo: [old-champagne](https://github.com/parth-soni07/old-champagne).

## AI tools disclosure

AI tools were used to build this project. Claude Code (Anthropic) helped with scaffolding, code,
tests and documentation. I reviewed, ran and verified all output, and I own the design decisions
and the analysis.

## Key definitions

- **Latest forecast available**: for each delivery day D (UK local), take the `WINDFOR` run with the
  greatest `publishTime` at or before **D-1 09:00 UK**. That is just before the 09:20 GB day-ahead
  auction gate. You can change the cutoff with the `cutoff` query parameter.
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

## API

| Endpoint | Returns |
|---|---|
| `GET /api/accuracy?cutoff=HH:MM` | Month metrics (MAE, RMSE, bias, MAPE, P90 shortfall), by day / hour / lead time / forecast level, error histogram, day-ahead lead window |
| `GET /api/day?date=YYYY-MM-DD&cutoff=HH:MM` | One delivery day: half-hourly actuals, the day-ahead forecast and its publish time, day metrics |
| `GET /docs` | Interactive OpenAPI docs |

`cutoff` defaults to `09:00` and must be `HH:MM`. `date` must fall inside the data (422 otherwise, with
the valid range in the message). Unknown `/api` paths return a JSON 404.

## Layout

| Path | What |
|---|---|
| `backend/analysis.py` | Day-ahead forecast selection (UK wall clock, clock-change safe) and accuracy metrics |
| `backend/app.py` | FastAPI app: input validation, security headers, opt-in CORS |
| `backend/fetch_data.py` | One-off pull of the January 2026 window from BMRS into `data/*.csv` |
| `backend/test_analysis.py` | Unit and edge-case tests: cutoff boundaries, UK clock changes, joins, metrics, real-data golden values |
| `backend/test_simulation.py` | Simulation tests: a synthetic month with known bias and noise, checked against the right answer |
| `backend/test_api.py` | HTTP contract, input validation (422s), security headers, CORS |
| `backend/test_fetch.py` | `fetch_data` dedupe and date windows with BMRS mocked out |
| `api/index.py` | Vercel Python entrypoint |
| `data/` | Committed BMRS snapshot (the data is historical, so it is not fetched live) |

## Run

```bash
# Docker (API on :8000)
docker build -t ethan . && docker run -p 8000:8000 -e ALLOWED_ORIGINS=http://localhost:3000 ethan

# Local (Python 3.12: pandas 2.2 has no wheels for 3.13+)
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
ALLOWED_ORIGINS=http://localhost:3000 .venv/bin/uvicorn backend.app:app --reload

# Tests (warnings are errors; config in pytest.ini) / refresh data
.venv/bin/pytest -q
.venv/bin/python -m backend.fetch_data
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `ALLOWED_ORIGINS` | unset (same-origin only) | Comma-separated origins allowed to call the API from a browser, e.g. the old-champagne deploy URL |
| `PORT` | `8000` | Port inside the Docker image |

## Deploy

`vercel deploy`: `vercel.json` runs `api/index.py` as a Python function and caches API responses at
the edge for a day (the data is static). Set `ALLOWED_ORIGINS` to the UI's URL. The Dockerfile also
runs as-is on any container host (non-root user, health check).
