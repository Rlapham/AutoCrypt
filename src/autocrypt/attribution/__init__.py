"""Lead-weighted wallet-attribution model (Phase 3) — the project's claimed edge.

Built so the kill-gate profiler can score the *wallet-attribution* thesis (Project_spec §2),
not just the derivative composite. Same survivorship-complete, point-in-time discipline.
"""

from autocrypt.attribution.signal import (
    AttributionResult,
    AttributionSignalConfig,
    compute_attribution,
)
from autocrypt.attribution.wallet_book import (
    AttributionConfig,
    WalletScore,
    WalletScoreBook,
)

__all__ = [
    "AttributionConfig",
    "AttributionResult",
    "AttributionSignalConfig",
    "WalletScore",
    "WalletScoreBook",
    "compute_attribution",
]
