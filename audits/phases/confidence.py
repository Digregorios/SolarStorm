"""Confidence-calibration audit emitter (Phase 5, T-5-5 / REQ-CONF-1 / REQ-MET-2).

Lives on the AUDITS side of the reverse-import guard (REQ-AUD-3): it MAY import
``core.confidence.score`` and ``core.contracts.phase5``; ``core/*`` must never import
this module.

Builds the REQ-CONF-1 audit surface on top of
``core.confidence.score.confidence_report`` (ECE + the selective
``bracket_match @ coverage`` table) and serializes it deterministically. It freezes
NO threshold: the documented ``ECE_TOL`` (0.05) gate is REPORTED via ``passed`` only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.confidence.score import ConfidenceConfig, confidence_report
from core.contracts.phase5 import ECE_TOL


def _coverage_key(cov: float) -> str:
    """Deterministic JSON key for a coverage point (floats are not stable map keys)."""
    return format(float(cov), ".2f")


def run_phase(
    *,
    confidence: Any,
    bracket_correct: Any,
    config: ConfidenceConfig = ConfidenceConfig(),
) -> dict[str, Any]:
    """Emit the confidence audit phase result.

    ``confidence`` is a sequence of calibrated scores in ``[0, 1]``;
    ``bracket_correct`` is the aligned binary label sequence. Both must be the same
    non-empty length (``confidence_report`` raises ``ValueError`` otherwise).

    Returns ``{"phase": "confidence", "passed": <ece <= ECE_TOL>, "details": {...}}``.
    ``passed`` is gated against the pre-registered contract ``ECE_TOL``, never a
    value tuned after seeing results.
    """
    report = confidence_report(confidence, bracket_correct, config=config)

    bm_table: dict[str, dict[str, float | int]] = {}
    for cov, (match_rate, n_kept) in report.bracket_match_by_coverage.items():
        bm_table[_coverage_key(cov)] = {
            "match_rate": float(match_rate),
            "n_kept": int(n_kept),
        }

    ece_within_tol = report.ece <= ECE_TOL
    return {
        "phase": "confidence",
        "passed": ece_within_tol,
        "details": {
            "ece": float(report.ece),
            "ece_tol": float(ECE_TOL),
            "ece_within_tol": ece_within_tol,
            "ece_bins": int(report.ece_bins),
            "n": int(report.n),
            "bracket_match_by_coverage": bm_table,
        },
    }


def write_confidence_audit(out_dir: Any, result: dict[str, Any]) -> Path:
    """Write ``confidence_audit.json`` into ``out_dir`` deterministically; return path.

    JSON is ASCII (``ensure_ascii=True``), ``sort_keys=True``, ``indent=2`` so that the
    same ``result`` yields byte-identical output. Creates ``out_dir`` if missing.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "confidence_audit.json"
    text = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2)
    path.write_text(text + "\n", encoding="ascii")
    return path


__all__ = ["run_phase", "write_confidence_audit"]
