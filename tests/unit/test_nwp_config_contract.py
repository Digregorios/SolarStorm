"""Config<->code contract test for NWP model specs (review D4).

The code ``ModelSpec`` constants are authoritative; ``nzwn/config/model.yaml`` is a
mirror. A divergent/dead config multiplies across phases, so ``load_nwp_model_specs``
asserts the two agree and the shipped config MUST pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.ingest.nwp_client import (
    ConfigContractError,
    ECMWF_IFS_HRES,
    V1_MODELS,
    load_nwp_model_specs,
)

REPO = Path(__file__).resolve().parents[2]
SHIPPED = REPO / "nzwn" / "config" / "model.yaml"


def test_shipped_model_yaml_matches_code():
    """The real nzwn/config/model.yaml must agree with code ModelSpecs."""
    specs = load_nwp_model_specs(SHIPPED)
    assert {s.id for s in specs} == {m.id for m in V1_MODELS}
    ecmwf = next(s for s in specs if s.id == "ecmwf_ifs_hres")
    # The exact value the original bug got wrong.
    assert ecmwf.open_meteo_id == "ecmwf_ifs"


def _write_yaml(tmp_path: Path, models: list[dict]) -> Path:
    doc = {"nwp": {"enabled": False, "models": models}}
    p = tmp_path / "model.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="ascii")
    return p


def _good_models() -> list[dict]:
    return [
        {"id": "ecmwf_ifs_hres", "open_meteo_id": "ecmwf_ifs", "cycle_h": 6,
         "archive_start": "2017-01-01"},
        {"id": "ncep_gfs_global", "open_meteo_id": "gfs_global", "cycle_h": 6,
         "archive_start": "2021-03-23"},
    ]


def test_wrong_open_meteo_id_is_rejected(tmp_path):
    models = _good_models()
    models[0]["open_meteo_id"] = "ecmwf_ifs_hres"  # the original bug
    p = _write_yaml(tmp_path, models)
    with pytest.raises(ConfigContractError, match="open_meteo_id"):
        load_nwp_model_specs(p)


def test_wrong_archive_start_is_rejected(tmp_path):
    models = _good_models()
    models[0]["archive_start"] = "2020-01-01"
    p = _write_yaml(tmp_path, models)
    with pytest.raises(ConfigContractError, match="archive_start"):
        load_nwp_model_specs(p)


def test_unknown_model_id_is_rejected(tmp_path):
    models = _good_models()
    models.append({"id": "ukmo_global", "open_meteo_id": "ukmo_global", "cycle_h": 6,
                   "archive_start": "2022-01-01"})
    p = _write_yaml(tmp_path, models)
    with pytest.raises(ConfigContractError, match="unknown|set"):
        load_nwp_model_specs(p)


def test_missing_model_is_rejected(tmp_path):
    models = _good_models()[:1]  # drop GFS
    p = _write_yaml(tmp_path, models)
    with pytest.raises(ConfigContractError, match="set"):
        load_nwp_model_specs(p)
