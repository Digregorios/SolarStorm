"""Phase 5 heteroscedasticity coverage gate (T-5-3, REQ-AUD-5, design 8.3).

Bins the emitted integer IC80 rows by their interval WIDTH into quantile bins
(quartiles by default) and checks empirical coverage per bin. The gate asserts
that interval width TRACKS difficulty: every width-quartile must cover within
``[low, high]``. It FAILS when at least one bin's coverage falls outside that
band -- the signature of heteroscedastic miscalibration is one (e.g. narrow) bin
out-of-band while another (e.g. wide) bin sits inside, exposed via the
``mixed_in_and_out`` flag.

Width per row is ``hi - lo + 1`` (integer brackets, matching
``conformal.coverage_report``). Coverage per bin is the fraction of rows with
``lo <= y_true <= hi``.

Tie / degenerate-width rule: bin edges are ``numpy.quantile`` of the unique
widths (deterministic, no RNG). When widths share values the quantile edges can
collide; rows are then assigned by ``numpy.searchsorted`` on the SORTED UNIQUE
widths, i.e. grouped by rank of distinct width rather than by raw count. Empty
bins (which arise when there are fewer distinct widths than ``n_bins``) are
dropped from the report; an all-identical-width input yields a single non-empty
bin. This keeps bins stable and reproducible and never crashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from core.contracts.phase5 import (
    HETEROSCED_COVERAGE_HIGH,
    HETEROSCED_COVERAGE_LOW,
    HETEROSCED_N_BINS,
)


@dataclass(frozen=True)
class HeteroscedasticityBin:
    """Coverage of one IC80 width-quantile bin."""

    bin_index: int
    width_lo: float
    width_hi: float
    coverage: float
    mean_width: float
    n: int


@dataclass(frozen=True)
class HeteroscedasticityReport:
    """Per-width-quartile coverage diagnostic (REQ-AUD-5 gate output).

    ``passed`` is True iff every non-empty bin's coverage lies within
    ``[low, high]``. ``mixed_in_and_out`` is True when at least one bin is inside
    the band AND at least one bin is outside it (the heteroscedastic signature).
    """

    passed: bool
    mixed_in_and_out: bool
    n_bins: int
    low: float
    high: float
    n: int
    bins: tuple[HeteroscedasticityBin, ...]


def heteroscedasticity_gate(
    ic80_low_int: Sequence[int],
    ic80_high_int: Sequence[int],
    y_true_int: Sequence[int],
    *,
    n_bins: int = HETEROSCED_N_BINS,
    low: float = HETEROSCED_COVERAGE_LOW,
    high: float = HETEROSCED_COVERAGE_HIGH,
) -> HeteroscedasticityReport:
    """Bin IC80 rows by width quartile and require per-bin coverage in [low, high].

    Width per row is ``hi - lo + 1`` integer brackets. See the module docstring
    for the tie / degenerate-width binning rule.
    """
    lo = np.asarray(ic80_low_int, dtype=int)
    hi = np.asarray(ic80_high_int, dtype=int)
    yt = np.asarray(y_true_int, dtype=int)
    if not (lo.size == hi.size == yt.size):
        raise ValueError(
            "ic80_low_int, ic80_high_int, y_true_int must be same length; "
            f"got {lo.size}, {hi.size}, {yt.size}"
        )
    if yt.size == 0:
        raise ValueError("cannot run heteroscedasticity gate on empty data")
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1; got {n_bins}")

    widths = (hi - lo + 1).astype(float)
    covered = (lo <= yt) & (yt <= hi)

    # Quantile edges over the UNIQUE widths so a heavily-tied distribution still
    # yields stable, rank-based interior cut points. searchsorted assigns each row
    # to the bin whose interior edges bracket its width.
    unique_widths = np.unique(widths)
    probs = np.linspace(0.0, 1.0, n_bins + 1)[1:-1]
    if probs.size:
        edges = np.quantile(unique_widths, probs, method="linear")
        bin_idx = np.searchsorted(edges, widths, side="right")
    else:
        bin_idx = np.zeros(widths.shape, dtype=int)

    bins: list[HeteroscedasticityBin] = []
    any_in = False
    any_out = False
    for b in range(n_bins):
        mask = bin_idx == b
        n_b = int(mask.sum())
        if n_b == 0:
            continue
        w = widths[mask]
        cov = float(covered[mask].mean())
        in_band = low <= cov <= high
        any_in = any_in or in_band
        any_out = any_out or (not in_band)
        bins.append(
            HeteroscedasticityBin(
                bin_index=b,
                width_lo=float(w.min()),
                width_hi=float(w.max()),
                coverage=cov,
                mean_width=float(w.mean()),
                n=n_b,
            )
        )

    passed = not any_out
    mixed_in_and_out = any_in and any_out
    return HeteroscedasticityReport(
        passed=passed,
        mixed_in_and_out=mixed_in_and_out,
        n_bins=n_bins,
        low=low,
        high=high,
        n=int(yt.size),
        bins=tuple(bins),
    )


__all__ = [
    "HeteroscedasticityBin",
    "HeteroscedasticityReport",
    "heteroscedasticity_gate",
]
