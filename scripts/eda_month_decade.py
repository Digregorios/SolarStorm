"""EDA: month x decade-of-month stratification of Tmax, late-warming, Tmax hour.

Read-only. Emits reports/eda/month_decade_{tmax,late_warming,tmax_hour}.md.
Walk-forward ridge/empirical bias per month and decade (test years 2023/2024/2025).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.features.builder import build_panel
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.io.timeutil import cp_to_utc
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_int as ridge_predict_int

REPO = Path(__file__).resolve().parents[1]


def decade_of_day(day: int) -> str:
    if day <= 10:
        return "D1"
    if day <= 20:
        return "D2"
    return "D3"


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    cp_op = cfg.cp_operational_utc
    obs, _ = load_observations(REPO / "NZWN.csv",
                               tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    l1_col = f"late_spike_l1__cp_{cp_op[:2]}"

    # Filter to complete days with valid tmax
    complete = labels.filter(pl.col("day_complete") & pl.col("tmax_int").is_not_null())

    # Precompute k_cp for each complete day (max tmp_c_int before cp_utc on that local date)
    kcp_map: dict[date, int | None] = {}
    obs_with_local = obs.filter(
        pl.col("dq_tmp_c_int") != "missing"
    ).with_columns(
        pl.col("ts_utc").dt.convert_time_zone(cfg.tz).dt.date().alias("date_local_obs")
    )
    for r in complete.iter_rows(named=True):
        d = r["date_local"]
        cp_utc_dt = cp_to_utc(d, cp_op)
        pre = obs_with_local.filter(
            (pl.col("date_local_obs") == d)
            & (pl.col("ts_utc") < cp_utc_dt)
            & pl.col("tmp_c_int").is_not_null()
        )
        kcp_map[d] = int(pre["tmp_c_int"].max()) if pre.height > 0 else None

    # --- Part 1: full-history stratification by (month, decade) ---
    cells: dict[tuple[int, str], list[dict]] = {}
    for r in complete.iter_rows(named=True):
        d = r["date_local"]
        key = (d.month, decade_of_day(d.day))
        cells.setdefault(key, []).append({
            "tmax_int": r["tmax_int"],
            "late_spike": r.get(l1_col),
            "tmax_hour": r["tmax_ts_local"].hour if r["tmax_ts_local"] is not None else None,
            "k_cp": kcp_map.get(d),
        })

    tmax_table = []
    lw_table = []
    hour_table = []
    for (m, dec) in sorted(cells.keys()):
        rr = cells[(m, dec)]
        n = len(rr)
        tmaxs = np.array([r["tmax_int"] for r in rr], dtype=float)
        mean_t = float(tmaxs.mean())
        med_t = float(np.median(tmaxs))
        p10 = float(np.percentile(tmaxs, 10))
        p90 = float(np.percentile(tmaxs, 90))
        tmax_table.append((m, dec, n, mean_t, med_t, p10, p90))

        # late spike rate (k_eod != k_cp)
        ls_vals = [r["late_spike"] for r in rr if r["late_spike"] is not None]
        ls_rate = sum(ls_vals) / len(ls_vals) if ls_vals else None

        # material late warming: k_eod - k_cp >= 2
        mlw_count = 0
        mlw_total = 0
        for r in rr:
            kcp = r["k_cp"]
            if kcp is None:
                continue
            mlw_total += 1
            if r["tmax_int"] - kcp >= 2:
                mlw_count += 1
        mlw_rate = mlw_count / mlw_total if mlw_total > 0 else None
        lw_table.append((m, dec, n, ls_rate, mlw_rate, mlw_count, mlw_total))

        # median tmax hour local
        hours = [r["tmax_hour"] for r in rr if r["tmax_hour"] is not None]
        med_hour = float(np.median(hours)) if hours else None
        p25_h = float(np.percentile(hours, 25)) if hours else None
        p75_h = float(np.percentile(hours, 75)) if hours else None
        hour_table.append((m, dec, n, med_hour, p25_h, p75_h))

    # --- Part 2: walk-forward bias by month and decade ---
    all_dates = [d for d in labels["date_local"].drop_nulls().unique().to_list()
                 if d is not None]
    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)])
    emp_panel_full = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)

    bias_rows: list[dict] = []
    for s in splits:
        climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=s.train_end)
        panel = build_training_panel(obs, labels, climo=climo, tz_name=cfg.tz,
                                     cp_set=cfg.cp_set_utc, dates=all_dates)
        op = panel.filter(panel["cp"] == cp_op)
        tr = op.filter((op["date_local"] >= s.train_start) & (op["date_local"] <= s.train_end))
        te = op.filter((op["date_local"] >= s.test_start) & (op["date_local"] <= s.test_end))
        if tr.height < 100:
            continue
        Xtr = np.column_stack([tr[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        ytr = tr["target_tmax_int"].to_numpy().astype(int)
        ctr = np.array([float(climo.tmax_dec_for(d)) for d in tr["date_local"].to_list()])
        fr = fit_ridge_band(Xtr, ytr, config=RidgeBandConfig(
            feature_columns=tuple(FEATURE_COLUMNS), use_climatology_anchor=True),
            clim_train=ctr)

        emp_tr = emp_panel_full.filter(
            (emp_panel_full["date_local"] >= s.train_start)
            & (emp_panel_full["date_local"] <= s.train_end))
        emp = fit_empirical_conditional(emp_tr, train_window=(s.train_start, s.train_end))

        Xte = np.column_stack([te[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        cte = np.array([float(climo.tmax_dec_for(d)) for d in te["date_local"].to_list()])
        ridge_p50 = ridge_predict_int(fr, Xte, clim=cte)

        sk = list(range(cfg.tmp_c_int_plausibility.min,
                        cfg.tmp_c_int_plausibility.max + 1))
        for i, row in enumerate(te.iter_rows(named=True)):
            d = row["date_local"]
            y = row["target_tmax_int"]
            if y is None:
                continue
            kcp_val = row["k_cp"]
            kcp_pred = int(kcp_val) if kcp_val is not None else Q(climo.tmax_dec_for(d))
            pd_e, _ = emp.predict_dist(month=d.month, cp=cp_op, k_cp=kcp_pred,
                                       support_k=sk)
            emp_p50 = max(pd_e.items(), key=lambda kv: kv[1])[0]
            bias_rows.append({
                "month": d.month,
                "decade": decade_of_day(d.day),
                "truth": int(y),
                "ridge_p50": int(ridge_p50[i]),
                "emp_p50": int(emp_p50),
            })

    # Aggregate bias
    bias_by_month: dict[int, dict[str, list]] = {}
    bias_by_decade: dict[str, dict[str, list]] = {}
    bias_by_md: dict[tuple[int, str], dict[str, list]] = {}
    for br in bias_rows:
        m = br["month"]
        dec = br["decade"]
        key = (m, dec)
        for store, k in [(bias_by_month, m), (bias_by_decade, dec), (bias_by_md, key)]:
            store.setdefault(k, {"ridge": [], "emp": []})
            store[k]["ridge"].append(br["truth"] - br["ridge_p50"])
            store[k]["emp"].append(br["truth"] - br["emp_p50"])

    # --- Emit reports ---
    out = REPO / "reports" / "eda"
    out.mkdir(parents=True, exist_ok=True)

    # Report 1: month_decade_tmax.md
    lines = ["# Tmax by (month, decade-of-month) - full history", "",
             "Decade: D1=days 1-10, D2=11-20, D3=21-end.", "",
             "| month | decade | n | mean_tmax | median | p10 | p90 |",
             "|-------|--------|---|-----------|--------|-----|-----|"]
    for (m, dec, n, mean_t, med_t, p10, p90) in tmax_table:
        lines.append(
            f"| {m:2d} | {dec} | {n:3d} | {mean_t:5.1f} | {med_t:4.0f} | "
            f"{p10:4.0f} | {p90:4.0f} |")
    lines += ["", "## Ridge bias by month (walk-forward OOS, signed = truth - p50)", "",
              "| month | n | ridge_bias | emp_bias |",
              "|-------|---|------------|----------|"]
    for m in sorted(bias_by_month.keys()):
        r_arr = np.array(bias_by_month[m]["ridge"])
        e_arr = np.array(bias_by_month[m]["emp"])
        lines.append(f"| {m:2d} | {len(r_arr):3d} | "
                     f"{r_arr.mean():+.3f} | {e_arr.mean():+.3f} |")
    lines += ["", "## Ridge bias by decade (walk-forward OOS)", "",
              "| decade | n | ridge_bias | emp_bias |",
              "|--------|---|------------|----------|"]
    for dec in ["D1", "D2", "D3"]:
        if dec in bias_by_decade:
            r_arr = np.array(bias_by_decade[dec]["ridge"])
            e_arr = np.array(bias_by_decade[dec]["emp"])
            lines.append(f"| {dec} | {len(r_arr):3d} | "
                         f"{r_arr.mean():+.3f} | {e_arr.mean():+.3f} |")
    # Headline
    spreads = []
    for m in range(1, 13):
        vals = [mean_t for (mm, _, _, mean_t, _, _, _) in tmax_table if mm == m]
        if len(vals) >= 2:
            spreads.append((m, max(vals) - min(vals)))
    max_spread = max(spreads, key=lambda x: x[1]) if spreads else (0, 0.0)
    lines += ["", "## Headline", "",
              f"Max intra-month mean_tmax spread: {max_spread[1]:.1f} degC "
              f"(month {max_spread[0]}).",
              "Typical spread < 1 degC => decade is a WEAK signal for Tmax level."]
    (out / "month_decade_tmax.md").write_text("\n".join(lines) + "\n", encoding="ascii")

    # Report 2: month_decade_late_warming.md
    lines = ["# Late-warming rate by (month, decade) - full history", "",
             "late_spike_rate = P(k_eod != k_cp at CP 23:00).",
             "material_late_warming_rate = P(k_eod - k_cp >= 2).", "",
             "| month | decade | n | late_spike | material_lw | mlw_n |",
             "|-------|--------|---|------------|-------------|-------|"]
    for (m, dec, n, ls, mlw, mlw_c, mlw_t) in lw_table:
        ls_s = f"{ls:.3f}" if ls is not None else "N/A"
        mlw_s = f"{mlw:.3f}" if mlw is not None else "N/A"
        lines.append(f"| {m:2d} | {dec} | {n:3d} | {ls_s} | "
                     f"{mlw_s} | {mlw_c}/{mlw_t} |")
    lw_spreads = []
    for m in range(1, 13):
        vals = [mlw for (mm, _, _, _, mlw, _, _) in lw_table
                if mm == m and mlw is not None]
        if len(vals) >= 2:
            lw_spreads.append((m, max(vals) - min(vals)))
    max_lw = max(lw_spreads, key=lambda x: x[1]) if lw_spreads else (0, 0.0)
    lines += ["", "## Headline", "",
              f"Max intra-month material_lw spread: {max_lw[1]:.3f} "
              f"(month {max_lw[0]}).",
              "If < 0.05 => decade adds negligible info beyond month for "
              "late-warming prediction."]
    (out / "month_decade_late_warming.md").write_text(
        "\n".join(lines) + "\n", encoding="ascii")

    # Report 3: month_decade_tmax_hour.md
    lines = ["# Tmax hour (local) by (month, decade) - full history", "",
             "| month | decade | n | median_hour | p25 | p75 |",
             "|-------|--------|---|-------------|-----|-----|"]
    for (m, dec, n, med_h, p25, p75) in hour_table:
        mh = f"{med_h:.1f}" if med_h is not None else "N/A"
        p25s = f"{p25:.1f}" if p25 is not None else "N/A"
        p75s = f"{p75:.1f}" if p75 is not None else "N/A"
        lines.append(f"| {m:2d} | {dec} | {n:3d} | {mh} | {p25s} | {p75s} |")
    lines += ["", "## Ridge bias by (month, decade) - walk-forward OOS", "",
              "| month | decade | n | ridge_bias | emp_bias |",
              "|-------|--------|---|------------|----------|"]
    for (m, dec) in sorted(bias_by_md.keys()):
        r_arr = np.array(bias_by_md[(m, dec)]["ridge"])
        e_arr = np.array(bias_by_md[(m, dec)]["emp"])
        lines.append(f"| {m:2d} | {dec} | {len(r_arr):3d} | "
                     f"{r_arr.mean():+.3f} | {e_arr.mean():+.3f} |")
    hour_spreads = []
    for m in range(1, 13):
        vals = [med_h for (mm, _, _, med_h, _, _) in hour_table
                if mm == m and med_h is not None]
        if len(vals) >= 2:
            hour_spreads.append((m, max(vals) - min(vals)))
    max_hs = max(hour_spreads, key=lambda x: x[1]) if hour_spreads else (0, 0.0)
    lines += ["", "## Headline", "",
              f"Max intra-month median_tmax_hour spread: {max_hs[1]:.1f}h "
              f"(month {max_hs[0]}).",
              "If < 1h => decade is NOT a useful Tmax-hour predictor beyond month.",
              "",
              "Does ridge_bias vary by (month, decade)?"]
    md_biases = [(k, float(np.mean(v["ridge"]))) for k, v in bias_by_md.items()]
    if md_biases:
        worst = max(md_biases, key=lambda x: abs(x[1]))
        lines.append(f"Worst (month,decade) ridge bias: {worst[1]:+.3f} at "
                     f"month={worst[0][0]} {worst[0][1]}.")
    (out / "month_decade_tmax_hour.md").write_text(
        "\n".join(lines) + "\n", encoding="ascii")

    # Optional JSON summary
    summary = {
        "tmax_table": [{"month": m, "decade": d, "n": n, "mean": round(mt, 2),
                        "median": int(med), "p10": int(p10), "p90": int(p90)}
                       for (m, d, n, mt, med, p10, p90) in tmax_table],
        "late_warming_table": [{"month": m, "decade": d, "n": n,
                                "late_spike_rate": round(ls, 4) if ls else None,
                                "material_lw_rate": round(mlw, 4) if mlw else None}
                               for (m, d, n, ls, mlw, _, _) in lw_table],
        "bias_by_month": {str(m): {"n": len(v["ridge"]),
                                   "ridge_bias": round(float(np.mean(v["ridge"])), 4),
                                   "emp_bias": round(float(np.mean(v["emp"])), 4)}
                          for m, v in bias_by_month.items()},
    }
    (out / "month_decade_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, default=str),
        encoding="ascii")

    print("Done. Reports in reports/eda/month_decade_*.md")
    print(f"Max intra-month mean_tmax spread: {max_spread[1]:.1f} degC "
          f"(month {max_spread[0]})")
    print(f"Max intra-month material_lw spread: {max_lw[1]:.3f} "
          f"(month {max_lw[0]})")
    print(f"Max intra-month median_tmax_hour spread: {max_hs[1]:.1f}h "
          f"(month {max_hs[0]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
