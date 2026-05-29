"""End-to-end smoke for Phase 1 + Phase 2 baselines on NZWN.csv.

Runs:
1) load_observations + ParseStats
2) snapshot_csv_by_local_day -> manifest
3) build_tmax_labels (REQ-CON-7 + late_spike_l1)
4) build_panel (CP-aware, closed='left')
5) fit_climatology (train-only)
6) fit_empirical_conditional + predict on a probe date
7) emit reports/eda/decimal_vs_int_check.md and reports/eda/coverage.md
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.station import load_station_config
from core.features.builder import build_panel
from core.ingest.iem_csv import load_observations
from core.ingest.snapshot import snapshot_csv_by_local_day
from core.io.hashing import sha256_file
from core.labels.tmax import build_tmax_labels


REPO = Path(__file__).resolve().parents[1]
CSV = REPO / "NZWN.csv"


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    print(f"[1/7] Loading {CSV.name} ...")
    obs, stats = load_observations(
        CSV,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    print(
        f"  rows={obs.height} ok={stats.n_parsed_ok} imputed={stats.n_parsed_imputed} "
        f"missing={stats.n_parsed_missing} fallback_rate={stats.fallback_rate:.5f}"
    )

    # Cross-check decimal vs integer for the rows where both are valid
    cross = obs.filter(
        (pl.col("dq_tmp_c_int") == "ok") & pl.col("tmpf").is_not_null()
    ).with_columns(
        (((pl.col("tmpf") - 32.0) * 5.0 / 9.0).round(0).cast(pl.Int32) - pl.col("tmp_c_int"))
        .alias("delta")
    )
    n_cross = cross.height
    n_disc = int(cross.filter(pl.col("delta") != 0).height)
    disc_rate = (n_disc / n_cross) if n_cross else 0.0
    print(f"  cross-check rows={n_cross} discrepancy={n_disc} rate={disc_rate:.5f}")

    # 2) Snapshot
    print("[2/7] Writing daily snapshots ...")
    src_sha = sha256_file(CSV)
    out_root = REPO / "artifacts" / "raw" / "metar"
    hashes = snapshot_csv_by_local_day(
        obs, station=cfg.icao, tz_name=cfg.tz, out_root=out_root, source_csv_sha256=src_sha
    )
    print(f"  snapshots={len(hashes)} manifest={out_root / 'manifest.jsonl'}")

    # 3) Labels
    print("[3/7] Building tmax labels ...")
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    n_complete = int(labels.filter(pl.col("day_complete")).height)
    n_total = labels.height
    cov_rate = n_complete / n_total
    print(f"  total_days={n_total} day_complete={n_complete} ratio={cov_rate:.4f}")

    # 4) Panel
    print("[4/7] Building CP panel (REQ-CON-5/AUD-4) ...")
    panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)
    print(f"  panel_rows={panel.height}")

    # 5) Climatology train-only
    train_start = date(2020, 1, 1)
    train_end = date(2024, 12, 31)
    test_start = date(2025, 1, 1)
    test_end = date(2025, 12, 31)
    print(f"[5/7] Fitting climatology (train {train_start}..{train_end}) ...")
    climo = fit_climatology(labels, train_start=train_start, train_end=train_end)
    p10, p90 = climo.percentiles_for(date(2025, 7, 1))
    print(f"  climo Jul p10={p10:.2f} p90={p90:.2f} n_train={climo.n_train_days}")

    # 6) Empirical baseline + probe
    print("[6/7] Fitting empirical conditional baseline ...")
    train_panel = panel.filter(
        (panel["date_local"] >= train_start) & (panel["date_local"] <= train_end)
    )
    empirical = fit_empirical_conditional(
        train_panel, train_window=(train_start, train_end)
    )
    probe_date = date(2025, 7, 15)  # winter
    pp10, pp90 = climo.percentiles_for(probe_date)
    sk = support_K(pp10, pp90, tmp_min=-10, tmp_max=40)
    probe_row = panel.filter(panel["date_local"] == probe_date)
    if probe_row.height:
        kcp = probe_row["k_cp__cp_23"][0]
        if kcp is not None:
            dist, src = empirical.predict_dist(
                month=probe_date.month, cp="23:00", k_cp=int(kcp), support_k=sk
            )
            p50 = max(dist.items(), key=lambda kv: kv[1])
            print(
                f"  probe {probe_date} k_cp={int(kcp)} support={sk[0]}..{sk[-1]} "
                f"p50={p50[0]} p={p50[1]:.4f} src={src}"
            )

    # 7) Persistence vs climatology gate (Phase 2 sanity)
    # Persistence: predict k_eod = k_cp at cp 23:00. Climatology: predict Q(climo).
    print("[7/7] Phase 2 sanity gate (persistence at 1h before EOD) ...")
    test_panel = panel.filter(
        (panel["date_local"] >= test_start)
        & (panel["date_local"] <= test_end)
        & panel["day_complete"]
        & panel["tmax_int"].is_not_null()
        & panel["k_cp__cp_23"].is_not_null()
    )
    n = test_panel.height
    if n:
        match = (test_panel["k_cp__cp_23"] == test_panel["tmax_int"]).sum()
        persistence_acc = match / n
        # Climatology persistence: predict Q(climo.tmax_dec_for(d)) for every test row
        clim_pred = [climo.tmax_dec_for(d) for d in test_panel["date_local"].to_list()]
        clim_int = [round(v) for v in clim_pred]
        truths = test_panel["tmax_int"].to_list()
        clim_match = sum(1 for c, t in zip(clim_int, truths, strict=True) if c == t)
        clim_acc = clim_match / n
        print(
            f"  test_n={n} persistence@cp23={persistence_acc:.4f} "
            f"climatology_int_acc={clim_acc:.4f}"
        )

    # 8) Coverage report
    coverage_md = REPO / "reports" / "eda" / "coverage.md"
    coverage_md.parent.mkdir(parents=True, exist_ok=True)
    monthly = (
        labels.with_columns(
            pl.col("date_local").dt.year().alias("year"),
            pl.col("date_local").dt.month().alias("month"),
        )
        .group_by(["year", "month"])
        .agg(
            pl.len().alias("n_total"),
            pl.col("day_complete").sum().alias("n_complete"),
        )
        .with_columns((pl.col("n_complete") / pl.col("n_total")).alias("ratio"))
        .sort(["year", "month"])
    )
    monthly.write_csv(REPO / "reports" / "eda" / "coverage_by_month.csv")
    coverage_md.write_text(
        f"# Coverage by month (REQ-CON-7)\n\n"
        f"- total_days: {n_total}\n"
        f"- day_complete: {n_complete}\n"
        f"- ratio: {cov_rate:.4f}\n\n"
        f"See `coverage_by_month.csv` for per-month breakdown.\n",
        encoding="ascii",
    )

    # 9) decimal_vs_int_check.md
    rep = REPO / "reports" / "eda" / "decimal_vs_int_check.md"
    rep.write_text(
        "# decimal_vs_int_check (REQ-CON-3 / REQ-CON-8)\n\n"
        f"- total_rows: {obs.height}\n"
        f"- parsed_ok: {stats.n_parsed_ok}\n"
        f"- parsed_imputed: {stats.n_parsed_imputed}\n"
        f"- parsed_missing: {stats.n_parsed_missing}\n"
        f"- fallback_rate_global: {stats.fallback_rate:.6f}\n\n"
        f"## Cross-check\n\n"
        f"- rows compared: {n_cross}\n"
        f"- discrepancies: {n_disc}\n"
        f"- discrepancy rate: {disc_rate:.6f}\n\n"
        f"Kill criterion (REQ-CON-8): fallback_rate <= 0.005 and discrepancy_rate <= 0.005.\n",
        encoding="ascii",
    )
    print(f"[done] reports written: {coverage_md} ; {rep}")
    print(
        json.dumps(
            {
                "fallback_rate": stats.fallback_rate,
                "discrepancy_rate": disc_rate,
                "day_complete_rate": cov_rate,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
