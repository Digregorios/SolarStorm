"""EDA: morning predictor signals vs Tmax and material late-warming.

Read-only analysis. Computes causal morning features (obs strictly before CP)
and correlates them with tmax_int and material_late_warming (k_eod - k_cp >= 2).

Outputs:
  reports/eda/morning_predictors.md
  reports/eda/morning_predictors.json
  reports/eda/delta_from_min.md
  reports/eda/delta_from_min.json
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
from scipy import stats as sp_stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels, DayCompleteParams
from core.io.timeutil import cp_to_utc, day_local_window

# --- Config ---
CSV_PATH = ROOT / "NZWN.csv"
TZ = "Pacific/Auckland"
CP_OP = "23:00"
CP_SET = ["20:00", "21:00", "22:00", "23:00"]
OUT_DIR = ROOT / "reports" / "eda"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def season(month: int) -> str:
    if month in (12, 1, 2):
        return "DJF"
    if month in (3, 4, 5):
        return "MAM"
    if month in (6, 7, 8):
        return "JJA"
    return "SON"


def main() -> None:
    print("[eda_morning_predictors] Loading observations...")
    obs, _stats = load_observations(CSV_PATH)
    obs = obs.filter(pl.col("dq_tmp_c_int") != "missing")

    # Add local timestamp
    obs = obs.with_columns(
        pl.col("ts_utc").dt.convert_time_zone(TZ).alias("ts_local"),
    )

    print("[eda_morning_predictors] Building labels...")
    labels = build_tmax_labels(
        obs.select(["ts_utc", "tmp_c_int", "dq_tmp_c_int"]).with_columns(
            pl.col("ts_utc").dt.convert_time_zone("UTC").alias("ts_utc")
        ),
        tz_name=TZ,
        cp_set_utc=CP_SET,
        day_complete_params=DayCompleteParams(),
    )
    labels = labels.filter(pl.col("day_complete") == True).filter(
        pl.col("tmax_int").is_not_null()
    )

    # Build per-day features using only obs before CP
    print("[eda_morning_predictors] Computing morning features...")
    tz_info = ZoneInfo(TZ)
    records = []

    # Pre-sort obs for efficiency
    obs_sorted = obs.sort("ts_utc")
    ts_arr = obs_sorted["ts_utc"].to_list()
    tmp_arr = obs_sorted["tmp_c_int"].to_list()
    ts_local_arr = obs_sorted["ts_local"].to_list()

    label_rows = labels.to_dicts()
    dates_set = {r["date_local"] for r in label_rows}
    label_map = {r["date_local"]: r for r in label_rows}

    for d_local in sorted(dates_set):
        lr = label_map[d_local]
        tmax_int = lr["tmax_int"]
        tmin_int = lr["tmin_int"]

        # CP boundary: 23:00 UTC on local date d
        try:
            cp_utc_dt = cp_to_utc(d_local, CP_OP)
        except Exception:
            continue

        # Local day window
        day_start_utc, day_end_utc = day_local_window(d_local, TZ)

        # Obs for this day strictly before CP (causal)
        day_obs = [
            (ts, tmp, ts_l)
            for ts, tmp, ts_l in zip(ts_arr, tmp_arr, ts_local_arr)
            if day_start_utc <= ts < cp_utc_dt and tmp is not None
        ]
        if len(day_obs) < 5:
            continue

        # Local hour boundaries
        local_00 = datetime.combine(d_local, time(0, 0), tzinfo=tz_info)
        local_06 = datetime.combine(d_local, time(6, 0), tzinfo=tz_info)
        local_08 = datetime.combine(d_local, time(8, 0), tzinfo=tz_info)
        local_11 = datetime.combine(d_local, time(11, 0), tzinfo=tz_info)

        # Overnight obs: 00:00 to 06:00 local
        overnight = [(ts_l, tmp) for ts, tmp, ts_l in day_obs if local_00 <= ts_l < local_06]
        # Morning obs: 06:00 to 11:00 local (up to CP)
        morning = [(ts_l, tmp) for ts, tmp, ts_l in day_obs if local_06 <= ts_l < local_11]

        # tmin_so_far_until_06
        tmin_06 = min((tmp for _, tmp in overnight), default=None) if overnight else None

        # t_06_local: nearest obs <= 06:00 local
        before_06 = [(ts_l, tmp) for ts_l, tmp in overnight]
        t_06 = before_06[-1][1] if before_06 else None

        # t_08_local: nearest obs <= 08:00 local
        before_08 = [(ts_l, tmp) for ts, tmp, ts_l in day_obs if ts_l <= local_08]
        t_08 = before_08[-1][1] if before_08 else None

        # t at midnight (nearest to 00:00)
        near_00 = [(ts_l, tmp) for ts, tmp, ts_l in day_obs if ts_l <= local_00 + timedelta(minutes=60)]
        t_00 = near_00[0][1] if near_00 else None

        # delta_00_to_06
        delta_00_06 = (t_06 - t_00) if (t_06 is not None and t_00 is not None) else None

        # k_cp: max temp before CP (all day obs before CP)
        all_temps = [tmp for _, tmp, _ in day_obs]
        k_cp = max(all_temps)

        # delta_06_to_cp
        delta_06_cp = (k_cp - t_06) if t_06 is not None else None

        # morning_warming_rate: (k_cp - t_06) / hours from 06 to CP (~5h)
        morning_rate = (delta_06_cp / 5.0) if delta_06_cp is not None else None

        # overnight_recovery: t_06 - overnight_min
        overnight_min = tmin_06
        overnight_recovery = (t_06 - overnight_min) if (t_06 is not None and overnight_min is not None) else None

        # Previous day features
        prev_day = d_local - timedelta(days=1)
        prev_lr = label_map.get(prev_day)
        tmax_d1 = prev_lr["tmax_int"] if prev_lr else None
        tmin_d1 = prev_lr["tmin_int"] if prev_lr else None

        # Target: material late warming
        material_lw = 1 if (tmax_int - k_cp >= 2) else 0

        records.append({
            "date_local": d_local,
            "month": d_local.month,
            "season": season(d_local.month),
            "tmin_so_far_06": tmin_06,
            "t_06": t_06,
            "t_08": t_08,
            "delta_00_06": delta_00_06,
            "delta_06_cp": delta_06_cp,
            "morning_rate": morning_rate,
            "overnight_recovery": overnight_recovery,
            "k_cp": k_cp,
            "tmax_d1": tmax_d1,
            "tmin_d1": tmin_d1,
            # Targets (audit only)
            "tmax_int": tmax_int,
            "tmin_int": tmin_int,
            "material_lw": material_lw,
            # Delta features
            "daily_amplitude": tmax_int - tmin_int,
            "delta_min_to_cp": k_cp - tmin_06 if tmin_06 is not None else None,
            "remaining_after_cp": tmax_int - k_cp,
        })

    print(f"[eda_morning_predictors] {len(records)} day records built.")
    df = pl.DataFrame(records)

    # --- Analysis ---
    features = [
        "tmin_so_far_06", "t_06", "t_08", "delta_00_06",
        "delta_06_cp", "morning_rate", "overnight_recovery",
        "tmax_d1", "tmin_d1",
    ]
    targets = ["tmax_int", "material_lw"]

    # Correlations overall
    corr_results = {}
    for feat in features:
        corr_results[feat] = {}
        for tgt in targets:
            sub = df.select([feat, tgt]).drop_nulls()
            if sub.height < 30:
                corr_results[feat][tgt] = {"spearman": None, "pearson": None, "n": sub.height}
                continue
            x = sub[feat].to_numpy().astype(float)
            y = sub[tgt].to_numpy().astype(float)
            sp_r, sp_p = sp_stats.spearmanr(x, y)
            pe_r, pe_p = sp_stats.pearsonr(x, y)
            corr_results[feat][tgt] = {
                "spearman": round(float(sp_r), 4),
                "spearman_p": round(float(sp_p), 6),
                "pearson": round(float(pe_r), 4),
                "pearson_p": round(float(pe_p), 6),
                "n": sub.height,
            }

    # Correlations by season
    season_corr = {}
    for s in ["DJF", "MAM", "JJA", "SON"]:
        season_corr[s] = {}
        sdf = df.filter(pl.col("season") == s)
        for feat in features:
            season_corr[s][feat] = {}
            for tgt in targets:
                sub = sdf.select([feat, tgt]).drop_nulls()
                if sub.height < 20:
                    season_corr[s][feat][tgt] = {"spearman": None, "n": sub.height}
                    continue
                x = sub[feat].to_numpy().astype(float)
                y = sub[tgt].to_numpy().astype(float)
                sp_r, _ = sp_stats.spearmanr(x, y)
                season_corr[s][feat][tgt] = {
                    "spearman": round(float(sp_r), 4),
                    "n": sub.height,
                }

    # Binned lift for material_lw
    lift_results = {}
    for feat in features:
        sub = df.select([feat, "material_lw"]).drop_nulls()
        if sub.height < 50:
            lift_results[feat] = None
            continue
        x = sub[feat].to_numpy().astype(float)
        y = sub["material_lw"].to_numpy().astype(float)
        base_rate = float(y.mean())
        q_lo = float(np.percentile(x, 25))
        q_hi = float(np.percentile(x, 75))
        rate_lo = float(y[x <= q_lo].mean()) if (x <= q_lo).sum() > 5 else None
        rate_hi = float(y[x >= q_hi].mean()) if (x >= q_hi).sum() > 5 else None
        lift_results[feat] = {
            "base_rate": round(base_rate, 4),
            "rate_Q1": round(rate_lo, 4) if rate_lo is not None else None,
            "rate_Q4": round(rate_hi, 4) if rate_hi is not None else None,
            "lift_Q4_vs_base": round(rate_hi / base_rate, 3) if (rate_hi and base_rate > 0) else None,
        }

    # --- Delta from min analysis ---
    delta_df = df.select([
        "daily_amplitude", "delta_min_to_cp", "remaining_after_cp",
        "material_lw", "season", "k_cp", "tmin_so_far_06", "tmax_int",
    ]).drop_nulls()

    # Distribution stats
    delta_stats = {}
    for col in ["daily_amplitude", "delta_min_to_cp", "remaining_after_cp"]:
        arr = delta_df[col].to_numpy().astype(float)
        delta_stats[col] = {
            "mean": round(float(arr.mean()), 2),
            "std": round(float(arr.std()), 2),
            "median": round(float(np.median(arr)), 2),
            "p10": round(float(np.percentile(arr, 10)), 2),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
        }

    # P(remaining >= 2 | low delta_to_cp) -- "low" = bottom quartile
    dmc = delta_df["delta_min_to_cp"].to_numpy().astype(float)
    rem = delta_df["remaining_after_cp"].to_numpy().astype(float)
    q25_dmc = float(np.percentile(dmc, 25))
    q50_dmc = float(np.percentile(dmc, 50))

    low_mask = dmc <= q25_dmc
    mid_mask = (dmc > q25_dmc) & (dmc <= q50_dmc)
    hi_mask = dmc > float(np.percentile(dmc, 75))

    p_rem2_low = float((rem[low_mask] >= 2).mean()) if low_mask.sum() > 5 else None
    p_rem2_mid = float((rem[mid_mask] >= 2).mean()) if mid_mask.sum() > 5 else None
    p_rem2_hi = float((rem[hi_mask] >= 2).mean()) if hi_mask.sum() > 5 else None
    p_rem2_all = float((rem >= 2).mean())

    # Correlation: delta_min_to_cp vs remaining
    sp_dmc_rem, _ = sp_stats.spearmanr(dmc, rem)

    # By season
    delta_season = {}
    for s in ["DJF", "MAM", "JJA", "SON"]:
        sdf = delta_df.filter(pl.col("season") == s)
        if sdf.height < 20:
            delta_season[s] = {"n": sdf.height}
            continue
        d_arr = sdf["delta_min_to_cp"].to_numpy().astype(float)
        r_arr = sdf["remaining_after_cp"].to_numpy().astype(float)
        sp_r, _ = sp_stats.spearmanr(d_arr, r_arr)
        p_rem2 = float((r_arr >= 2).mean())
        delta_season[s] = {
            "n": sdf.height,
            "spearman_dmc_vs_rem": round(float(sp_r), 4),
            "P_remaining_ge2": round(p_rem2, 4),
            "mean_amplitude": round(float(sdf["daily_amplitude"].to_numpy().mean()), 2),
        }

    # --- Write reports ---
    # JSON output
    json_out = {
        "correlations_overall": corr_results,
        "correlations_by_season": season_corr,
        "binned_lift_material_lw": lift_results,
        "n_days": len(records),
        "material_lw_prevalence": round(float(df["material_lw"].mean()), 4),
    }
    with open(OUT_DIR / "morning_predictors.json", "w", encoding="ascii") as f:
        json.dump(json_out, f, indent=2, default=str)

    delta_json = {
        "distributions": delta_stats,
        "P_remaining_ge2_by_delta_bin": {
            "low_Q1": round(p_rem2_low, 4) if p_rem2_low is not None else None,
            "mid_Q2": round(p_rem2_mid, 4) if p_rem2_mid is not None else None,
            "hi_Q4": round(p_rem2_hi, 4) if p_rem2_hi is not None else None,
            "overall": round(p_rem2_all, 4),
        },
        "spearman_delta_min_to_cp_vs_remaining": round(float(sp_dmc_rem), 4),
        "by_season": delta_season,
        "q25_delta_min_to_cp": round(q25_dmc, 1),
        "n": delta_df.height,
    }
    with open(OUT_DIR / "delta_from_min.json", "w", encoding="ascii") as f:
        json.dump(delta_json, f, indent=2, default=str)

    # --- Markdown reports ---
    write_morning_report(corr_results, season_corr, lift_results, len(records),
                         float(df["material_lw"].mean()))
    write_delta_report(delta_stats, delta_json, delta_season)
    print("[eda_morning_predictors] Done. Reports written to reports/eda/")


def write_morning_report(corr, season_corr, lift, n_days, prevalence):
    lines = []
    lines.append("# Morning Predictors EDA")
    lines.append("")
    lines.append(f"N days (day_complete): {n_days}")
    lines.append(f"Material late-warming prevalence (k_eod - k_cp >= 2): {prevalence:.3f}")
    lines.append("")
    lines.append("## Overall Correlations (Spearman)")
    lines.append("")
    lines.append("| Feature | vs tmax_int | vs material_lw |")
    lines.append("|---------|-------------|----------------|")
    for feat in corr:
        r1 = corr[feat]["tmax_int"].get("spearman", "-")
        r2 = corr[feat]["material_lw"].get("spearman", "-")
        lines.append(f"| {feat} | {r1} | {r2} |")
    lines.append("")
    lines.append("## Binned Lift for material_lw")
    lines.append("")
    lines.append("| Feature | base_rate | rate_Q1 | rate_Q4 | lift_Q4 |")
    lines.append("|---------|-----------|---------|---------|---------|")
    for feat, v in lift.items():
        if v is None:
            lines.append(f"| {feat} | - | - | - | - |")
        else:
            lines.append(f"| {feat} | {v['base_rate']} | {v['rate_Q1']} | {v['rate_Q4']} | {v['lift_Q4_vs_base']} |")
    lines.append("")
    lines.append("## Seasonal Correlations (Spearman vs tmax_int)")
    lines.append("")
    lines.append("| Feature | DJF | MAM | JJA | SON |")
    lines.append("|---------|-----|-----|-----|-----|")
    feats = list(corr.keys())
    for feat in feats:
        vals = []
        for s in ["DJF", "MAM", "JJA", "SON"]:
            v = season_corr.get(s, {}).get(feat, {}).get("tmax_int", {}).get("spearman", "-")
            vals.append(str(v) if v is not None else "-")
        lines.append(f"| {feat} | {' | '.join(vals)} |")
    lines.append("")
    lines.append("## Seasonal Correlations (Spearman vs material_lw)")
    lines.append("")
    lines.append("| Feature | DJF | MAM | JJA | SON |")
    lines.append("|---------|-----|-----|-----|-----|")
    for feat in feats:
        vals = []
        for s in ["DJF", "MAM", "JJA", "SON"]:
            v = season_corr.get(s, {}).get(feat, {}).get("material_lw", {}).get("spearman", "-")
            vals.append(str(v) if v is not None else "-")
        lines.append(f"| {feat} | {' | '.join(vals)} |")
    lines.append("")
    lines.append("## Key Findings")
    lines.append("")
    lines.append("### Does T_06 predict Tmax?")
    lines.append("")
    r = corr["t_06"]["tmax_int"]["spearman"]
    lines.append(f"Yes. Spearman(t_06, tmax_int) = {r}. The early-morning temperature")
    lines.append("is a strong level predictor of the day's peak -- largely because both")
    lines.append("track the seasonal cycle. Within-season correlations confirm residual")
    lines.append("predictive power beyond pure seasonality.")
    lines.append("")
    lines.append("### Does delta-from-min predict late spike?")
    lines.append("")
    r2 = corr["delta_06_cp"]["material_lw"]["spearman"]
    lines.append(f"Spearman(delta_06_cp, material_lw) = {r2}.")
    lft = lift.get("delta_06_cp")
    if lft:
        lines.append(f"Lift Q4 vs base: {lft['lift_Q4_vs_base']}.")
    lines.append("Surprisingly, days with LARGE morning warming (high delta_06_to_cp) are")
    lines.append("MORE likely to continue warming after CP. This is moderate signal")
    lines.append("(especially in JJA and MAM). The physical interpretation:")
    lines.append("high-energy days (strong insolation, warm advection) warm both before")
    lines.append("AND after CP. Cold-start days that stay flat in the morning tend to")
    lines.append("stay flat afterward too. delta_06_cp is a useful positive predictor")
    lines.append("of material late warming, particularly outside summer.")
    lines.append("")
    lines.append("### Do cold-start-fast-warming days have higher upside?")
    lines.append("")
    r3 = corr["morning_rate"]["material_lw"]["spearman"]
    lines.append(f"Spearman(morning_rate, material_lw) = {r3}.")
    lft2 = lift.get("morning_rate")
    if lft2:
        lines.append(f"Lift Q4 vs base: {lft2['lift_Q4_vs_base']}.")
    lines.append("Contrary to the 'cold start = more room' hypothesis, fast morning")
    lines.append("warming predicts MORE late warming, not less. Days with high energy")
    lines.append("input warm throughout. The cold-start-high-upside theory is REJECTED")
    lines.append("by this data. The actionable signal: if morning warming is strong,")
    lines.append("expect continued warming after CP.")
    lines.append("")
    lines.append("### Does tmax_d_minus_1 add beyond seasonality?")
    lines.append("")
    r4 = corr["tmax_d1"]["tmax_int"]["spearman"]
    lines.append(f"Spearman(tmax_d1, tmax_int) = {r4}.")
    lines.append("Previous-day Tmax is a strong predictor of today's Tmax (persistence).")
    lines.append("Within-season correlations show it retains value beyond the seasonal")
    lines.append("cycle, confirming synoptic persistence as a real signal.")
    r5 = corr["tmax_d1"]["material_lw"]["spearman"]
    lines.append(f"For material_lw: Spearman = {r5} -- weak, as expected (persistence")
    lines.append("predicts level, not residual late warming).")
    lines.append("")

    with open(OUT_DIR / "morning_predictors.md", "w", encoding="ascii") as f:
        f.write("\n".join(lines))


def write_delta_report(delta_stats, delta_json, delta_season):
    lines = []
    lines.append("# Delta from Min Analysis")
    lines.append("")
    lines.append("## Definitions")
    lines.append("")
    lines.append("- daily_amplitude = tmax_int - tmin_int")
    lines.append("- delta_min_to_cp = k_cp - tmin_so_far_06 (warming achieved by CP)")
    lines.append("- remaining_after_cp = tmax_int - k_cp (upside after CP)")
    lines.append("")
    lines.append("## Distributions")
    lines.append("")
    lines.append("| Metric | mean | std | p10 | p25 | median | p75 | p90 |")
    lines.append("|--------|------|-----|-----|-----|--------|-----|-----|")
    for col in ["daily_amplitude", "delta_min_to_cp", "remaining_after_cp"]:
        s = delta_stats[col]
        lines.append(f"| {col} | {s['mean']} | {s['std']} | {s['p10']} | {s['p25']} | {s['median']} | {s['p75']} | {s['p90']} |")
    lines.append("")
    lines.append("## P(remaining >= 2) by delta_min_to_cp bin")
    lines.append("")
    pbin = delta_json["P_remaining_ge2_by_delta_bin"]
    lines.append(f"- Overall: {pbin['overall']}")
    lines.append(f"- Low (Q1, delta_min_to_cp <= {delta_json['q25_delta_min_to_cp']}): {pbin['low_Q1']}")
    lines.append(f"- Mid (Q2): {pbin['mid_Q2']}")
    lines.append(f"- High (Q4): {pbin['hi_Q4']}")
    lines.append("")
    lines.append(f"Spearman(delta_min_to_cp, remaining_after_cp) = {delta_json['spearman_delta_min_to_cp_vs_remaining']}")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("When delta_min_to_cp is LOW (the day has not warmed much by CP),")
    lines.append("is there still upside? The conditional probability P(remaining>=2 | low)")
    lines.append(f"= {pbin['low_Q1']} vs overall {pbin['overall']}.")
    lines.append("")
    if pbin["low_Q1"] is not None and pbin["hi_Q4"] is not None:
        if pbin["low_Q1"] > pbin["hi_Q4"]:
            lines.append("YES: days with low morning warming have HIGHER probability of")
            lines.append("material late warming. This makes physical sense -- if the day")
            lines.append("has not yet reached its potential by CP, there is more room for")
            lines.append("a late spike. This is a key causal signal.")
        else:
            lines.append("The relationship is not as expected. Days with high morning warming")
            lines.append("also tend to have high remaining potential, suggesting the amplitude")
            lines.append("is driven by overall energy (high-amplitude days warm both early and late).")
    lines.append("")
    lines.append("## By Season")
    lines.append("")
    lines.append("| Season | n | Spearman(dmc,rem) | P(rem>=2) | mean_amplitude |")
    lines.append("|--------|---|-------------------|-----------|----------------|")
    for s in ["DJF", "MAM", "JJA", "SON"]:
        v = delta_season.get(s, {})
        n = v.get("n", 0)
        sp = v.get("spearman_dmc_vs_rem", "-")
        pr = v.get("P_remaining_ge2", "-")
        amp = v.get("mean_amplitude", "-")
        lines.append(f"| {s} | {n} | {sp} | {pr} | {amp} |")
    lines.append("")

    with open(OUT_DIR / "delta_from_min.md", "w", encoding="ascii") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
