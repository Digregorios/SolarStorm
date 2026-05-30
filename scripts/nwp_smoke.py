"""Quick smoke: sanity check NWP snapshots after backfill."""

from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl

from core.ingest.nwp import read_snapshots, select_nwp_v1, select_nwp_ensemble
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "artifacts" / "raw" / "nwp"

for model in [ECMWF_IFS_HRES, NCEP_GFS]:
    df = read_snapshots(station="NZWN", model=model, endpoint="hfapi", out_root=ROOT)
    print(f"{model.id}: rows={df.height}", end=" ")
    if df.height:
        print(
            f"valid_time={df['valid_time_utc'].min()} .. {df['valid_time_utc'].max()} "
            f"unique_runs={df['run_time_utc'].n_unique()}"
        )
    else:
        print("EMPTY")

# Test selection at a sample CP
all_snaps = read_snapshots(station="NZWN", model=None, endpoint="hfapi", out_root=ROOT)
print(f"\nAll-models rows: {all_snaps.height}")
cp = datetime(2025, 7, 14, 23, tzinfo=timezone.utc)  # 11:00 NZST
target = datetime(2025, 7, 15, 2, tzinfo=timezone.utc)  # ~14:00 NZST (Tmax hour climo proxy)
sel = select_nwp_ensemble(
    all_snaps, cp_utc=cp, target_valid_utc=target,
    models=["ecmwf_ifs_hres", "ncep_gfs_global"],
)
for m, s in sel.items():
    print(f"  {m}: {s}")
