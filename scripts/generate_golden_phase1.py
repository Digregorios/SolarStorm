"""Generate golden fixtures for Phase 1 (T-1-9).

Produces 3 representative days (summer, winter, DST transition) under
``tests/golden/phase1/`` with frozen labels + features.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core.contracts.station import load_station_config
from core.features.builder import build_cp_features
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels


REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "phase1"


def _serialise_label_row(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, (bool, int, float, str)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def main() -> int:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    cases = {
        "summer_2025_01_15": date(2025, 1, 15),
        "winter_2024_07_15": date(2024, 7, 15),
        "dst_end_2025_04_06": date(2025, 4, 6),
    }
    for name, d in cases.items():
        row = labels.filter(labels["date_local"] == d)
        if row.height != 1:
            print(f"SKIP {name}: no single label for {d}")
            continue
        label_dict = _serialise_label_row(row.row(0, named=True))
        feats_per_cp = {}
        for cp in cfg.cp_set_utc:
            try:
                f = build_cp_features(obs, date_local=d, cp_hhmm=cp, tz_name=cfg.tz, labels=labels)
                # Strip tz info for ASCII serialisation safety
                feats_per_cp[cp] = {
                    "cp_utc": f.cp_utc.isoformat(),
                    "feature_max_ts_utc": f.feature_max_ts_utc.isoformat(),
                    "k_cp": f.features.get("k_cp"),
                    "t_so_far_max_c_int": f.features.get("t_so_far_max_c_int"),
                    "last_obs_tmp_c_int": f.features.get("last_obs_tmp_c_int"),
                }
            except Exception as exc:  # noqa: BLE001
                feats_per_cp[cp] = {"error": str(exc)}

        payload = {
            "date_local": d.isoformat(),
            "label": label_dict,
            "cp_features": feats_per_cp,
        }
        out_path = GOLDEN / f"{name}.json"
        with open(out_path, "w", encoding="ascii") as fh:
            json.dump(payload, fh, ensure_ascii=True, sort_keys=True, indent=2)
        print(f"OK: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
