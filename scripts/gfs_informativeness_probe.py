"""GFS gridpoint informativeness probe (reviewer gate (a) for Phase-4 Option 1).

Question this answers: at the NZWN gridpoint, does GFS day-to-day variation track
observed Tmax, or is the 0.25deg cell dominated by the sea so the daily signal is
washed out? This GATES whether Option 1 (GFS-everywhere causal anchor via S3+eccodes)
is even worth building. It is NOT a causal/leakage claim -- we deliberately use the
already-on-disk HFAPI snapshots (stitched, leakage-prone) because if even the
*optimistic* stitched GFS can't track observed Tmax, the stricter causal GRIB anchor
certainly won't. So this is a cheap upper-bound feasibility check, exactly as the
review prescribes ("probe de minutos em poucas datas").

Method (per local date d, Pacific/Auckland):
  - gfs_tmax_proxy(d) = max over GFS valid_time in the local-day window of t2m_c.
  - obs_tmax(d)       = observed integer Tmax from labels (day_complete only).
  - Report Pearson + Spearman of the *day-to-day* series for GFS and ECMWF, per year
    (the 3 Phase-4 splits: 2023, 2024, 2025) and pooled, plus a maritime-damping
    diagnostic: std(gfs_proxy) vs std(obs_tmax) and the regression slope (a slope
    well below 1 with low corr = the cell is averaging out the land signal).

Output: reports/gfs_probe.json + a human summary to stdout (ASCII only).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels

TZ = ZoneInfo("Pacific/Auckland")
NWP_ROOT = Path("artifacts/raw/nwp/NZWN")
CP_SET = ["20:00", "21:00", "22:00", "23:00"]
SPLIT_YEARS = [2023, 2024, 2025]
MODELS = {"gfs": "ncep_gfs_global", "ecmwf": "ecmwf_ifs_hres"}


def _read_model_year(model_dir: str, year: int) -> pl.DataFrame:
    frames = []
    ydir = NWP_ROOT / model_dir / "hfapi" / str(year)
    if not ydir.exists():
        return pl.DataFrame()
    for mfile in sorted(ydir.glob("*.parquet")):
        frames.append(pl.read_parquet(mfile))
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical_relaxed")


def _gfs_daily_max(df: pl.DataFrame) -> pl.DataFrame:
    """Daily max of t2m_c over the local-day window, deduping stitched runs.

    valid_time_utc is converted to local; for each local date we take the max t2m_c
    across all valid times that fall in that local day. Multiple runs cover the same
    valid hour -- we keep the max (a daily-peak proxy is robust to which run supplied
    the hour, since we only need a peak estimate)."""
    if df.is_empty():
        return df
    d = df.filter(pl.col("t2m_c").is_not_null()).with_columns(
        pl.col("valid_time_utc").dt.convert_time_zone("Pacific/Auckland").alias("vt_local")
    ).with_columns(pl.col("vt_local").dt.date().alias("date_local"))
    return d.group_by("date_local").agg(pl.col("t2m_c").max().alias("nwp_tmax_proxy")).sort("date_local")


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx = np.argsort(np.argsort(x))
    ry = np.argsort(np.argsort(y))
    return _pearson(rx.astype(float), ry.astype(float))


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    # OLS slope of obs (y) on nwp (x): how many degC obs moves per degC of nwp.
    if len(x) < 3 or np.std(x) == 0:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def main() -> int:
    obs, _stats = load_observations("NZWN.csv")
    labels = build_tmax_labels(obs, tz_name="Pacific/Auckland", cp_set_utc=CP_SET)
    labels = labels.filter(pl.col("day_complete") & pl.col("tmax_int").is_not_null())
    lab = labels.select(["date_local", "tmax_int"])

    results: dict[str, object] = {"per_year": {}, "pooled": {}}
    pooled: dict[str, list[float]] = {"gfs_nwp": [], "gfs_obs": [], "ecmwf_nwp": [], "ecmwf_obs": []}

    for key, mdir in MODELS.items():
        for year in SPLIT_YEARS:
            raw = _read_model_year(mdir, year)
            if raw.is_empty():
                results["per_year"].setdefault(str(year), {})[key] = {"status": "no_data"}
                continue
            daily = _gfs_daily_max(raw)
            joined = daily.join(lab, on="date_local", how="inner").drop_nulls()
            n = joined.height
            if n < 10:
                results["per_year"].setdefault(str(year), {})[key] = {"status": "too_few", "n": n}
                continue
            xnwp = joined["nwp_tmax_proxy"].to_numpy().astype(float)
            yobs = joined["tmax_int"].to_numpy().astype(float)
            results["per_year"].setdefault(str(year), {})[key] = {
                "status": "ok",
                "n": n,
                "pearson": round(_pearson(xnwp, yobs), 4),
                "spearman": round(_spearman(xnwp, yobs), 4),
                "slope_obs_on_nwp": round(_slope(xnwp, yobs), 4),
                "std_nwp": round(float(np.std(xnwp)), 4),
                "std_obs": round(float(np.std(yobs)), 4),
                "mean_bias_nwp_minus_obs": round(float(np.mean(xnwp - yobs)), 4),
            }
            pooled[f"{key}_nwp"].extend(xnwp.tolist())
            pooled[f"{key}_obs"].extend(yobs.tolist())

    for key in MODELS:
        xn = np.array(pooled[f"{key}_nwp"])
        yo = np.array(pooled[f"{key}_obs"])
        if len(xn) >= 10:
            results["pooled"][key] = {
                "n": int(len(xn)),
                "pearson": round(_pearson(xn, yo), 4),
                "spearman": round(_spearman(xn, yo), 4),
                "slope_obs_on_nwp": round(_slope(xn, yo), 4),
                "std_nwp": round(float(np.std(xn)), 4),
                "std_obs": round(float(np.std(yo)), 4),
            }

    out = Path("reports/gfs_probe.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str), encoding="ascii")

    # ASCII human summary
    print("=== GFS gridpoint informativeness probe (HFAPI upper-bound) ===")
    print("question: does NWP daily-max proxy track observed Tmax day-to-day at NZWN?")
    print("")
    for key in MODELS:
        print(f"[{key.upper()}]")
        for year in SPLIT_YEARS:
            r = results["per_year"].get(str(year), {}).get(key)
            if not r or r.get("status") != "ok":
                print(f"  {year}: {r.get('status') if r else 'missing'}")
                continue
            print(
                f"  {year}: n={r['n']:3d}  pearson={r['pearson']:+.3f}  "
                f"spearman={r['spearman']:+.3f}  slope={r['slope_obs_on_nwp']:+.2f}  "
                f"std_nwp={r['std_nwp']:.2f} std_obs={r['std_obs']:.2f}  "
                f"bias={r['mean_bias_nwp_minus_obs']:+.2f}"
            )
        p = results["pooled"].get(key)
        if p:
            print(
                f"  POOLED: n={p['n']:3d}  pearson={p['pearson']:+.3f}  "
                f"spearman={p['spearman']:+.3f}  slope={p['slope_obs_on_nwp']:+.2f}"
            )
        print("")
    print("interpretation:")
    print("  pearson >> 0 and slope near 1 -> gridpoint carries the land Tmax signal (Option 1 viable).")
    print("  pearson low and slope << 1    -> maritime cell damps the signal (Option 1 likely dies; -> Option 2).")
    print("  wrote reports/gfs_probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
