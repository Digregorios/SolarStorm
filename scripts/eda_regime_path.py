"""Regime-path EDA: causal pre-CP proxies vs material late warming.

Computes heuristic regime proxies from ONLY pre-CP observations and cuts
material_late_warming (k_eod - k_cp >= 2) by each proxy.

Output:
  reports/regime/regime_path_eda.md
  reports/regime/foehn_clearing_rain_recovery_eda.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest.iem_csv import read_iem_csv, parse_observations  # noqa: E402
from core.labels.tmax import build_tmax_labels, DayCompleteParams  # noqa: E402

# --- Config ---
CSV_PATH = ROOT / "NZWN.csv"
TZ = "Pacific/Auckland"
CP_OP = "23:00"
CP_SET = ["20:00", "21:00", "22:00", "23:00"]
OUT_DIR = ROOT / "reports" / "regime"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def wind_quadrant(drct):
    """N/E/S/W from degrees (None if missing)."""
    if drct is None or drct != drct:
        return None
    d = drct % 360
    if d >= 315 or d < 45:
        return "N"
    elif d < 135:
        return "E"
    elif d < 225:
        return "S"
    else:
        return "W"


def sky_score(skyc):
    """Numeric cloud cover: CLR/FEW=0, SCT=1, BKN=2, OVC=3."""
    if skyc is None:
        return None
    s = str(skyc).strip().upper()
    if s in ("CLR", "SKC", "FEW", "NSC", "CAVOK", ""):
        return 0
    if s == "SCT":
        return 1
    if s == "BKN":
        return 2
    if s == "OVC":
        return 3
    return None


def main():
    # --- Load raw data ---
    raw = read_iem_csv(CSV_PATH)
    obs, _stats = parse_observations(raw)

    # Add local time
    obs = obs.with_columns(
        pl.col("ts_utc").dt.convert_time_zone(TZ).alias("ts_local"),
    ).with_columns(
        pl.col("ts_local").dt.date().alias("date_local"),
        pl.col("ts_local").dt.hour().alias("hour_local"),
    )

    # --- Build labels ---
    labels = build_tmax_labels(
        obs, tz_name=TZ, cp_set_utc=CP_SET,
        day_complete_params=DayCompleteParams(min_obs=40, max_gap_minutes=120, min_quartile_coverage=1),
    )
    labels = labels.filter(pl.col("day_complete"))

    # --- Per-day pre-CP feature extraction ---
    # For each day, get obs strictly before CP (23:00 UTC = ~11:00 local)
    # We need k_cp per day too
    # Join labels with per-day obs aggregation

    # Collect per-day features using python loop for clarity
    days = labels.select("date_local", "tmax_int", "tmax_ts_utc").to_dicts()

    # Pre-filter obs to only valid tmp rows for k_cp
    obs_valid = obs.filter(pl.col("dq_tmp_c_int") != "missing")

    # Build a dict: date_local -> list of obs rows (pre-CP)
    # For efficiency, add cp_utc per date and filter
    from datetime import datetime, timezone, time, timedelta
    from zoneinfo import ZoneInfo

    tz_obj = ZoneInfo(TZ)

    results = []
    # Convert obs to dicts grouped by date for speed
    obs_py = obs.select(
        "ts_utc", "date_local", "hour_local", "tmp_c_int", "tmpf",
        "drct", "sknt", "dwpf", "p01i", "alti", "skyc1", "wxcodes",
    ).to_dicts()

    # Group by date_local
    from collections import defaultdict
    day_obs = defaultdict(list)
    for r in obs_py:
        day_obs[r["date_local"]].append(r)

    for day_row in days:
        d = day_row["date_local"]
        tmax_int = day_row["tmax_int"]
        tmax_ts_utc = day_row["tmax_ts_utc"]

        # CP datetime in UTC
        local_start = datetime.combine(d, time(0, 0, 0), tzinfo=tz_obj)
        # CP is 23:00 UTC; find which falls in this local day
        day_start_utc = local_start.astimezone(timezone.utc)
        # CP candidates
        cp_candidates = [
            datetime(day_start_utc.year, day_start_utc.month, day_start_utc.day, 23, 0, 0, tzinfo=timezone.utc),
            datetime(day_start_utc.year, day_start_utc.month, day_start_utc.day, 23, 0, 0, tzinfo=timezone.utc) + timedelta(days=1),
        ]
        day_end_utc = (local_start + timedelta(days=1)).astimezone(timezone.utc)
        cp_utc = None
        for c in cp_candidates:
            if day_start_utc <= c < day_end_utc:
                cp_utc = c
                break
        if cp_utc is None:
            continue

        all_obs = day_obs.get(d, [])
        # Pre-CP obs (strictly before)
        pre_cp = [r for r in all_obs if r["ts_utc"] < cp_utc]
        if len(pre_cp) < 5:
            continue

        # k_cp
        valid_temps_pre = [r["tmp_c_int"] for r in pre_cp if r["tmp_c_int"] is not None]
        if not valid_temps_pre:
            continue
        k_cp_val = max(valid_temps_pre)
        k_eod = tmax_int
        if k_eod is None:
            continue
        delta_k = k_eod - k_cp_val

        # tmax_hour (local)
        tmax_hour = None
        if tmax_ts_utc is not None:
            tmax_local = tmax_ts_utc.astimezone(tz_obj)
            tmax_hour = tmax_local.hour
        cp_hour_local = cp_utc.astimezone(tz_obj).hour

        # --- Window splits ---
        # local 00-06, 06-09, 09-CP(~11)
        w1 = [r for r in pre_cp if r["hour_local"] is not None and 0 <= r["hour_local"] < 6]
        w2 = [r for r in pre_cp if r["hour_local"] is not None and 6 <= r["hour_local"] < 9]
        w3 = [r for r in pre_cp if r["hour_local"] is not None and 9 <= r["hour_local"] <= cp_hour_local]

        # --- Wind quadrant ---
        # At CP: use last 1h before CP
        last_hour = [r for r in pre_cp if r["ts_utc"] >= cp_utc - timedelta(hours=1)]
        drct_vals_cp = [r["drct"] for r in last_hour if r["drct"] is not None]
        wq_cp = None
        if drct_vals_cp:
            # Mode quadrant
            quads = [wind_quadrant(d_) for d_ in drct_vals_cp]
            quads = [q for q in quads if q is not None]
            if quads:
                wq_cp = max(set(quads), key=quads.count)

        # Wind quadrant in w1 (00-06)
        drct_w1 = [r["drct"] for r in w1 if r["drct"] is not None]
        wq_w1 = None
        if drct_w1:
            quads_w1 = [wind_quadrant(d_) for d_ in drct_w1]
            quads_w1 = [q for q in quads_w1 if q is not None]
            if quads_w1:
                wq_w1 = max(set(quads_w1), key=quads_w1.count)

        # Wind quadrant change
        wq_change = f"{wq_w1}->{wq_cp}" if wq_w1 and wq_cp else None

        # --- Wind speed mean (pre-CP) ---
        sknt_vals = [r["sknt"] for r in pre_cp if r["sknt"] is not None]
        wind_speed_mean = sum(sknt_vals) / len(sknt_vals) if sknt_vals else None

        # --- Dewpoint depression ---
        def dd_vals(window):
            out = []
            for r in window:
                if r["tmpf"] is not None and r["dwpf"] is not None:
                    out.append((r["tmpf"] - r["dwpf"]) * 5.0 / 9.0)
            return out

        dd_w1 = dd_vals(w1)
        dd_w3 = dd_vals(w3)
        dd_mean = None
        dd_trend = None
        dd_all = dd_vals(pre_cp)
        if dd_all:
            dd_mean = sum(dd_all) / len(dd_all)
        if dd_w1 and dd_w3:
            dd_trend = (sum(dd_w3) / len(dd_w3)) - (sum(dd_w1) / len(dd_w1))

        # --- QNH (alti) trend ---
        alti_w1 = [r["alti"] for r in w1 if r["alti"] is not None]
        alti_w3 = [r["alti"] for r in w3 if r["alti"] is not None]
        alti_trend = None
        if alti_w1 and alti_w3:
            alti_trend = (sum(alti_w3) / len(alti_w3)) - (sum(alti_w1) / len(alti_w1))

        # --- Rain recent (last 3h pre-CP) ---
        last_3h = [r for r in pre_cp if r["ts_utc"] >= cp_utc - timedelta(hours=3)]
        rain_recent = False
        for r in last_3h:
            if r["p01i"] is not None and r["p01i"] > 0:
                rain_recent = True
                break
            if r["wxcodes"] is not None and "RA" in str(r["wxcodes"]).upper():
                rain_recent = True
                break

        # --- Rain stopped (rain earlier but not last hour) ---
        last_1h = [r for r in pre_cp if r["ts_utc"] >= cp_utc - timedelta(hours=1)]
        earlier = [r for r in pre_cp if r["ts_utc"] < cp_utc - timedelta(hours=1)]
        rain_earlier = False
        for r in earlier:
            if r["p01i"] is not None and r["p01i"] > 0:
                rain_earlier = True
                break
            if r["wxcodes"] is not None and "RA" in str(r["wxcodes"]).upper():
                rain_earlier = True
                break
        rain_last_1h = False
        for r in last_1h:
            if r["p01i"] is not None and r["p01i"] > 0:
                rain_last_1h = True
                break
            if r["wxcodes"] is not None and "RA" in str(r["wxcodes"]).upper():
                rain_last_1h = True
                break
        rain_stopped = rain_earlier and not rain_last_1h

        # --- Clearing proxy ---
        # Cloud cover decreasing: BKN/OVC earlier -> FEW/SCT/CLR near CP
        sky_earlier = [sky_score(r["skyc1"]) for r in earlier if sky_score(r["skyc1"]) is not None]
        sky_last_1h = [sky_score(r["skyc1"]) for r in last_1h if sky_score(r["skyc1"]) is not None]
        clearing_proxy = False
        if sky_earlier and sky_last_1h:
            avg_earlier = sum(sky_earlier) / len(sky_earlier)
            avg_last = sum(sky_last_1h) / len(sky_last_1h)
            clearing_proxy = (avg_earlier >= 2.0) and (avg_last <= 1.0)

        # --- Foehn-like proxy ---
        # NW wind + rising temp + falling dewpoint depression (drying)
        foehn_like = False
        if wq_cp in ("N", "W"):
            # Rising temp in w3 vs w1
            tmp_w1 = [r["tmpf"] for r in w1 if r["tmpf"] is not None]
            tmp_w3 = [r["tmpf"] for r in w3 if r["tmpf"] is not None]
            if tmp_w1 and tmp_w3:
                temp_rising = (sum(tmp_w3) / len(tmp_w3)) > (sum(tmp_w1) / len(tmp_w1))
                # Falling dewpoint depression means drying (dd increasing)
                dd_falling = dd_trend is not None and dd_trend > 1.0
                if temp_rising and dd_falling:
                    foehn_like = True

        # --- Coarse regime path ---
        # Characterize each window
        def window_char(window):
            rain = any(
                (r["p01i"] is not None and r["p01i"] > 0) or
                (r["wxcodes"] is not None and "RA" in str(r["wxcodes"]).upper())
                for r in window
            )
            sky_vals = [sky_score(r["skyc1"]) for r in window if sky_score(r["skyc1"]) is not None]
            cloudy = (sum(sky_vals) / len(sky_vals) >= 2.0) if sky_vals else False
            dd_w = dd_vals(window)
            dry = (sum(dd_w) / len(dd_w) > 5.0) if dd_w else False
            if rain:
                return "rainy"
            elif cloudy:
                return "cloudy"
            elif dry:
                return "dry"
            else:
                return "mild"

        c1 = window_char(w1) if w1 else "?"
        c2 = window_char(w2) if w2 else "?"
        c3 = window_char(w3) if w3 else "?"
        regime_path = f"{c1}->{c2}->{c3}"

        results.append({
            "date": d,
            "k_cp": k_cp_val,
            "k_eod": k_eod,
            "delta_k": delta_k,
            "material_late_warming": delta_k >= 2,
            "tmax_hour": tmax_hour,
            "tmax_after_cp": tmax_hour > cp_hour_local if tmax_hour is not None else None,
            "wq_cp": wq_cp,
            "wq_change": wq_change,
            "wind_speed_mean": wind_speed_mean,
            "dd_mean": dd_mean,
            "dd_trend": dd_trend,
            "alti_trend": alti_trend,
            "rain_recent": rain_recent,
            "rain_stopped": rain_stopped,
            "clearing_proxy": clearing_proxy,
            "foehn_like": foehn_like,
            "regime_path": regime_path,
        })

    df = pl.DataFrame(results)
    n_total = df.height
    base_rate = df["material_late_warming"].sum() / n_total if n_total > 0 else 0
    base_e_delta = df["delta_k"].mean() if n_total > 0 else 0
    base_tmax_after = df["tmax_after_cp"].sum() / df["tmax_after_cp"].drop_nulls().len() if n_total > 0 else 0

    print(f"N days (day_complete): {n_total}")
    print(f"Base rate P(delta_k>=2): {base_rate:.4f}")
    print(f"Base E[delta_k]: {base_e_delta:.3f}")
    print(f"Base P(tmax_after_cp): {base_tmax_after:.4f}")

    # --- Cuts ---
    def cut_by(col, label):
        """Return list of dicts with stats per group."""
        rows = []
        groups = df.group_by(col).agg(
            pl.col("material_late_warming").mean().alias("p_mlw"),
            pl.col("material_late_warming").sum().alias("n_mlw"),
            pl.col("delta_k").mean().alias("e_delta"),
            pl.col("tmax_after_cp").mean().alias("p_tmax_after"),
            pl.len().alias("n"),
        ).sort(col)
        for r in groups.to_dicts():
            val = r[col]
            p = r["p_mlw"] if r["p_mlw"] is not None else 0
            rows.append({
                "proxy": label,
                "value": str(val),
                "n": r["n"],
                "p_mlw": round(p, 4),
                "lift": round(p / base_rate, 2) if base_rate > 0 else None,
                "e_delta_k": round(r["e_delta"], 3) if r["e_delta"] is not None else None,
                "p_tmax_after": round(r["p_tmax_after"], 4) if r["p_tmax_after"] is not None else None,
            })
        return rows

    cuts_wq = cut_by("wq_cp", "wind_quadrant_cp")
    cuts_wqc = cut_by("wq_change", "wind_quadrant_change")
    cuts_clearing = cut_by("clearing_proxy", "clearing_proxy")
    cuts_foehn = cut_by("foehn_like", "foehn_like")
    cuts_rain_stopped = cut_by("rain_stopped", "rain_stopped")
    cuts_regime = cut_by("regime_path", "regime_path")

    # --- Write reports ---
    # 1. regime_path_eda.md
    lines = [
        "# Regime Path EDA",
        "",
        f"N days (day_complete): {n_total}",
        f"Base rate P(k_eod - k_cp >= 2): {base_rate:.4f}",
        f"Base E[delta_k]: {base_e_delta:.3f}",
        f"Base P(tmax_hour > cp_hour): {base_tmax_after:.4f}",
        "",
        "## Regime Path Cuts",
        "",
        "| regime_path | n | P(mlw) | lift | E[delta_k] | P(tmax_after) |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(cuts_regime, key=lambda x: -(x["lift"] or 0)):
        lines.append(
            f"| {r['value']} | {r['n']} | {r['p_mlw']} | {r['lift']} | {r['e_delta_k']} | {r['p_tmax_after']} |"
        )

    lines += [
        "",
        "## Regime Path Transition Table (count)",
        "",
    ]
    # Transition table: w1_char -> w3_char counts
    regime_parts = df.select("regime_path").to_series().to_list()
    from collections import Counter
    trans = Counter()
    for rp in regime_parts:
        parts = rp.split("->")
        if len(parts) == 3:
            trans[(parts[0], parts[2])] += 1
    w1_vals = sorted(set(k[0] for k in trans.keys()))
    w3_vals = sorted(set(k[1] for k in trans.keys()))
    lines.append("| w1 \\ w3 | " + " | ".join(w3_vals) + " |")
    lines.append("|---|" + "|".join(["---"] * len(w3_vals)) + "|")
    for w1 in w1_vals:
        row_vals = [str(trans.get((w1, w3), 0)) for w3 in w3_vals]
        lines.append(f"| {w1} | " + " | ".join(row_vals) + " |")

    (OUT_DIR / "regime_path_eda.md").write_text("\n".join(lines), encoding="ascii")
    print(f"Wrote {OUT_DIR / 'regime_path_eda.md'}")

    # 2. foehn_clearing_rain_recovery_eda.md
    all_cuts = cuts_wq + cuts_wqc + cuts_clearing + cuts_foehn + cuts_rain_stopped
    lines2 = [
        "# Foehn / Clearing / Rain-Recovery EDA",
        "",
        f"N days: {n_total}",
        f"Base rate P(k_eod - k_cp >= 2): {base_rate:.4f}",
        f"Base E[delta_k]: {base_e_delta:.3f}",
        f"Base P(tmax_hour > cp_hour): {base_tmax_after:.4f}",
        "",
        "## Individual Proxy Cuts",
        "",
        "| proxy | value | n | P(mlw) | lift | E[delta_k] | P(tmax_after) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(all_cuts, key=lambda x: -(x["lift"] or 0)):
        lines2.append(
            f"| {r['proxy']} | {r['value']} | {r['n']} | {r['p_mlw']} | {r['lift']} | {r['e_delta_k']} | {r['p_tmax_after']} |"
        )

    # Summary: top lift proxies
    lines2 += [
        "",
        "## Top Lift Proxies (vs base rate)",
        "",
    ]
    top = sorted(all_cuts, key=lambda x: -(x["lift"] or 0))[:10]
    for i, r in enumerate(top, 1):
        lines2.append(f"{i}. **{r['proxy']}={r['value']}**: lift={r['lift']}, P(mlw)={r['p_mlw']}, n={r['n']}")

    (OUT_DIR / "foehn_clearing_rain_recovery_eda.md").write_text("\n".join(lines2), encoding="ascii")
    print(f"Wrote {OUT_DIR / 'foehn_clearing_rain_recovery_eda.md'}")

    # Optional JSON dump
    summary = {
        "n_days": n_total,
        "base_rate_mlw": round(base_rate, 4),
        "base_e_delta_k": round(base_e_delta, 3),
        "base_p_tmax_after": round(base_tmax_after, 4),
        "cuts": all_cuts + cuts_regime,
    }
    (OUT_DIR / "regime_eda_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="ascii"
    )
    print(f"Wrote {OUT_DIR / 'regime_eda_summary.json'}")


if __name__ == "__main__":
    main()
