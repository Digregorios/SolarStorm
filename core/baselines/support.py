"""Support K - integer candidates for prob_dist (design 4.5.1).

K is derived from min(climo_p10, nwp_p10) - 2 to max(climo_p90, nwp_p90) + 2,
truncated to plausibility bounds [tmp_min, tmp_max].
"""

from __future__ import annotations

import math


def support_K(
    climo_p10: float,
    climo_p90: float,
    *,
    nwp_p10: float | None = None,
    nwp_p90: float | None = None,
    tmp_min: int = -10,
    tmp_max: int = 40,
) -> list[int]:
    p10 = climo_p10 if nwp_p10 is None else min(climo_p10, nwp_p10)
    p90 = climo_p90 if nwp_p90 is None else max(climo_p90, nwp_p90)
    if p10 > p90:
        p10, p90 = p90, p10
    k_min = math.floor(p10 + 0.5) - 2
    k_max = math.floor(p90 + 0.5) + 2
    k_min = max(k_min, tmp_min)
    k_max = min(k_max, tmp_max)
    if k_min > k_max:
        # degenerate; widen by 1 each side within bounds
        k_min = max(tmp_min, k_min - 1)
        k_max = min(tmp_max, k_max + 1)
    return list(range(int(k_min), int(k_max) + 1))


__all__ = ["support_K"]
