"""Phase 4 pre-registration hash with teeth (C3, design 29.4 step 5).

``contracts/phase4_preregistration.md`` freezes the decision tree, thresholds,
seeds and fold boundaries. We hash ONLY the canonical block delimited by the
``<<<PREREG`` / ``PREREG>>>`` markers, so prose around it can be clarified without a
version bump while substance cannot drift silently.

``phase4_evaluate`` calls ``assert_preregistration_committed`` at startup and exits
non-zero if the runtime hash != ``COMMITTED_SHA256``. Editing anything inside the
markers therefore forces a deliberate, reviewable update of ``COMMITTED_SHA256`` in
this file - a tracked act, not a quiet edit. That is the whole point: a moving
pre-registration is no pre-registration.
"""

from __future__ import annotations

from pathlib import Path

from core.io.hashing import sha256_text


REPO = Path(__file__).resolve().parents[2]
PREREG_PATH = REPO / "contracts" / "phase4_preregistration.md"
PHASE5_PREREG_PATH = REPO / "contracts" / "phase5_preregistration.md"
PHASE5A_PREREG_PATH = REPO / "contracts" / "phase5_amendment.md"
PHASE5A3_PREREG_PATH = REPO / "contracts" / "phase5_amendment_trackA_a3.md"
PHASE5P_PREREG_PATH = (
    REPO / "contracts" / "phase5_amendment_trackP_predictive_uncertainty.md"
)
PHASE5PP_PREREG_PATH = (
    REPO / "contracts" / "phase5_amendment_trackPprime_quantization_margin.md"
)
PHASE5D1_PREREG_PATH = (
    REPO / "contracts" / "phase5_amendment_trackD_d1_randomized_Q.md"
)

_BEGIN = "<<<PREREG"
_END = "PREREG>>>"

# Pinned hash of the canonical PREREG block. If you intentionally change the
# pre-registration, recompute via ``python -m core.eval.preregistration`` and paste
# the new value here IN THE SAME COMMIT as the contract edit.
COMMITTED_SHA256 = "9a0a2a1b7ebbd0398cf578c86c1874f29139b3b141b024c127d504a400a1b29f"

# Phase 5 conformal-method amendment (criterion_version 1.0). Recompute via
# ``python -m core.eval.preregistration phase5`` and paste here in the SAME change as
# any edit to the phase5 PREREG block.
PHASE5_COMMITTED_SHA256 = "56459f40e94a4162b850419f6920ad73afd8a3bc371dc3924c503f6beb01cea1"

# Phase 5 Track A.A1 amendment (sigma winsorization; conformal_method_version 1.1).
# Recompute via ``python -m core.eval.preregistration phase5a`` and paste here in the
# SAME change as any edit to the phase5_amendment PREREG block.
PHASE5A_COMMITTED_SHA256 = "ea5b279a70c9b889158c10a867a35a6b49b7859402fa01661cd082b0a6e39c09"

# Phase 5 Track A.A3 amendment (Mondrian conditional conformal by sigma bucket;
# conformal_method_version 1.2). Recompute via
# ``python -m core.eval.preregistration phase5a3`` and paste here in the SAME change as any
# edit to the phase5_amendment_trackA_a3 PREREG block.
PHASE5A3_COMMITTED_SHA256 = "ee0ac6f232490b749eaac27cbb974a58446d4b6db15fc96be607ae5a8b87e411"

# Phase 5 Track P amendment (predictive-distribution uncertainty as the difficulty axis;
# conformal_method_version 1.3). Recompute via
# ``python -m core.eval.preregistration phase5p`` and paste here in the SAME change as any
# edit to the phase5_amendment_trackP_predictive_uncertainty PREREG block.
PHASE5P_COMMITTED_SHA256 = "215c29d34d582cf619d2766e69b5e55cb9c452a68e89e1613619d71aef759b85"

# Phase 5 Track P' amendment (quantization margin / distance-to-threshold as the difficulty
# axis; conformal_method_version 1.4). Recompute via
# ``python -m core.eval.preregistration phase5pp`` and paste here in the SAME change as any
# edit to the phase5_amendment_trackPprime_quantization_margin PREREG block.
PHASE5PP_COMMITTED_SHA256 = "e4fb58abb8ce63b67527ba4b906c6ab783506220e27c75023a91cc63db07c4e4"

# Phase 5 Track D.D1 amendment (randomized rounding / tie-breaking at quantization;
# conformal_method_version 2.0, q_version 1.1). The frozen Q_rand definition was corrected
# pre-execution from a biased factor-2 transcription to the unbiased standard randomized
# rounding (P(ceil)=t); this hash is over the corrected canonical block. Recompute via
# ``python -m core.eval.preregistration phase5d1`` and paste here in the SAME change as any
# edit to the phase5_amendment_trackD_d1_randomized_Q PREREG block.
PHASE5D1_COMMITTED_SHA256 = "7e14915e6e7b51f701aad79f736c65cf12303d038a866cdf14e245ed3e4ccb4b"


class PreregistrationError(RuntimeError):
    """Raised when the runtime pre-registration hash != the committed hash."""


def extract_canonical_block(text: str) -> str:
    """Return the normalized canonical block between the PREREG markers.

    The markers must each occupy their OWN line (surrounding whitespace ignored).
    Prose that only *mentions* the marker tokens inline - e.g. the contract's own
    explanatory header, which references them in backticks - therefore cannot be
    mistaken for the real delimiters. Normalization: CRLF/CR -> LF, rstrip each
    line, and trim blank lines adjacent to the markers, making the hash robust to
    line-ending churn but sensitive to any change in the frozen values.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    begin_idx = end_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == _BEGIN:
            begin_idx = i
            break
    if begin_idx is not None:
        for j in range(begin_idx + 1, len(lines)):
            if lines[j].strip() == _END:
                end_idx = j
                break
    if begin_idx is None or end_idx is None:
        raise PreregistrationError(
            f"pre-registration markers {_BEGIN!r}/{_END!r} not found on their own lines"
        )
    block = [ln.rstrip() for ln in lines[begin_idx + 1 : end_idx]]
    while block and block[0] == "":
        block.pop(0)
    while block and block[-1] == "":
        block.pop()
    return "\n".join(block) + "\n"


def preregistration_sha256(path: str | Path = PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the committed contract file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_preregistration_committed(path: str | Path = PREREG_PATH) -> str:
    """Assert the runtime hash matches ``COMMITTED_SHA256``; return the hash.

    Raises ``PreregistrationError`` (caller maps to non-zero exit) on mismatch.
    """
    runtime = preregistration_sha256(path)
    if runtime != COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 4 pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {COMMITTED_SHA256}\n"
            "The frozen pre-registration changed. If intentional, update "
            "COMMITTED_SHA256 in core/eval/preregistration.py in the SAME commit "
            "as the contract edit; otherwise revert the contract change."
        )
    return runtime


def phase5_preregistration_sha256(path: str | Path = PHASE5_PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the Phase 5 contract file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_phase5_preregistration_committed(path: str | Path = PHASE5_PREREG_PATH) -> str:
    """Assert the Phase 5 runtime hash matches ``PHASE5_COMMITTED_SHA256``."""
    runtime = phase5_preregistration_sha256(path)
    if runtime != PHASE5_COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 5 pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {PHASE5_COMMITTED_SHA256}\n"
            "The frozen Phase 5 pre-registration changed. If intentional, update "
            "PHASE5_COMMITTED_SHA256 in core/eval/preregistration.py in the SAME "
            "commit as the contract edit; otherwise revert the contract change."
        )
    return runtime


def phase5a_preregistration_sha256(path: str | Path = PHASE5A_PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the Phase 5 Track A.A1 amendment file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_phase5a_preregistration_committed(path: str | Path = PHASE5A_PREREG_PATH) -> str:
    """Assert the Track A.A1 runtime hash matches ``PHASE5A_COMMITTED_SHA256``."""
    runtime = phase5a_preregistration_sha256(path)
    if runtime != PHASE5A_COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 5 Track A.A1 pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {PHASE5A_COMMITTED_SHA256}\n"
            "The frozen Track A.A1 pre-registration changed. If intentional, update "
            "PHASE5A_COMMITTED_SHA256 in core/eval/preregistration.py in the SAME "
            "commit as the contract edit; otherwise revert the contract change."
        )
    return runtime


def phase5a3_preregistration_sha256(path: str | Path = PHASE5A3_PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the Phase 5 Track A.A3 amendment file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_phase5a3_preregistration_committed(path: str | Path = PHASE5A3_PREREG_PATH) -> str:
    """Assert the Track A.A3 runtime hash matches ``PHASE5A3_COMMITTED_SHA256``."""
    runtime = phase5a3_preregistration_sha256(path)
    if runtime != PHASE5A3_COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 5 Track A.A3 pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {PHASE5A3_COMMITTED_SHA256}\n"
            "The frozen Track A.A3 pre-registration changed. If intentional, update "
            "PHASE5A3_COMMITTED_SHA256 in core/eval/preregistration.py in the SAME "
            "commit as the contract edit; otherwise revert the contract change."
        )
    return runtime


def phase5p_preregistration_sha256(path: str | Path = PHASE5P_PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the Phase 5 Track P amendment file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_phase5p_preregistration_committed(path: str | Path = PHASE5P_PREREG_PATH) -> str:
    """Assert the Track P runtime hash matches ``PHASE5P_COMMITTED_SHA256``."""
    runtime = phase5p_preregistration_sha256(path)
    if runtime != PHASE5P_COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 5 Track P pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {PHASE5P_COMMITTED_SHA256}\n"
            "The frozen Track P pre-registration changed. If intentional, update "
            "PHASE5P_COMMITTED_SHA256 in core/eval/preregistration.py in the SAME "
            "commit as the contract edit; otherwise revert the contract change."
        )
    return runtime


def phase5pp_preregistration_sha256(path: str | Path = PHASE5PP_PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the Phase 5 Track P' amendment file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_phase5pp_preregistration_committed(path: str | Path = PHASE5PP_PREREG_PATH) -> str:
    """Assert the Track P' runtime hash matches ``PHASE5PP_COMMITTED_SHA256``."""
    runtime = phase5pp_preregistration_sha256(path)
    if runtime != PHASE5PP_COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 5 Track P' pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {PHASE5PP_COMMITTED_SHA256}\n"
            "The frozen Track P' pre-registration changed. If intentional, update "
            "PHASE5PP_COMMITTED_SHA256 in core/eval/preregistration.py in the SAME "
            "commit as the contract edit; otherwise revert the contract change."
        )
    return runtime


def phase5d1_preregistration_sha256(path: str | Path = PHASE5D1_PREREG_PATH) -> str:
    """SHA256 of the canonical PREREG block of the Phase 5 Track D.D1 amendment file."""
    text = Path(path).read_text(encoding="ascii")
    return sha256_text(extract_canonical_block(text))


def assert_phase5d1_preregistration_committed(path: str | Path = PHASE5D1_PREREG_PATH) -> str:
    """Assert the Track D.D1 runtime hash matches ``PHASE5D1_COMMITTED_SHA256``."""
    runtime = phase5d1_preregistration_sha256(path)
    if runtime != PHASE5D1_COMMITTED_SHA256:
        raise PreregistrationError(
            "Phase 5 Track D.D1 pre-registration hash mismatch.\n"
            f"  runtime  : {runtime}\n"
            f"  committed: {PHASE5D1_COMMITTED_SHA256}\n"
            "The frozen Track D.D1 pre-registration changed. If intentional, update "
            "PHASE5D1_COMMITTED_SHA256 in core/eval/preregistration.py in the SAME "
            "commit as the contract edit; otherwise revert the contract change."
        )
    return runtime


__all__ = [
    "COMMITTED_SHA256",
    "PHASE5_COMMITTED_SHA256",
    "PHASE5A_COMMITTED_SHA256",
    "PHASE5A3_COMMITTED_SHA256",
    "PHASE5P_COMMITTED_SHA256",
    "PHASE5PP_COMMITTED_SHA256",
    "PHASE5D1_COMMITTED_SHA256",
    "PreregistrationError",
    "PREREG_PATH",
    "PHASE5_PREREG_PATH",
    "PHASE5A_PREREG_PATH",
    "PHASE5A3_PREREG_PATH",
    "PHASE5P_PREREG_PATH",
    "PHASE5PP_PREREG_PATH",
    "extract_canonical_block",
    "preregistration_sha256",
    "assert_preregistration_committed",
    "phase5_preregistration_sha256",
    "assert_phase5_preregistration_committed",
    "phase5a_preregistration_sha256",
    "assert_phase5a_preregistration_committed",
    "phase5a3_preregistration_sha256",
    "assert_phase5a3_preregistration_committed",
    "phase5p_preregistration_sha256",
    "assert_phase5p_preregistration_committed",
    "phase5pp_preregistration_sha256",
    "assert_phase5pp_preregistration_committed",
    "phase5d1_preregistration_sha256",
    "assert_phase5d1_preregistration_committed",
]


if __name__ == "__main__":
    import sys

    which = sys.argv[1] if len(sys.argv) > 1 else "phase4"
    if which == "phase5":
        print(phase5_preregistration_sha256())
    elif which == "phase5a":
        print(phase5a_preregistration_sha256())
    elif which == "phase5a3":
        print(phase5a3_preregistration_sha256())
    elif which == "phase5p":
        print(phase5p_preregistration_sha256())
    elif which == "phase5pp":
        print(phase5pp_preregistration_sha256())
    elif which == "phase5d1":
        print(phase5d1_preregistration_sha256())
    else:
        print(preregistration_sha256())
