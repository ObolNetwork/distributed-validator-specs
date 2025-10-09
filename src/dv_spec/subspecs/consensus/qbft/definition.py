import math
from dv_spec.types.base import StrictBaseModel
from dv_spec.types.duty import Duty


class Definition(StrictBaseModel):
    """
    QBFT consensus system parameters and computed properties.
    This remains constant across multiple instances of consensus.
    """

    nodes: int
    """Total number of nodes in the consensus cluster."""

    def quorum(self) -> int:
        """Calculate quorum size."""
        return int(math.ceil(float(self.nodes * 2) / 3))

    def faulty(self) -> int:
        """Calculate maximum number of faulty nodes."""
        return int(math.floor(float(self.nodes - 1) / 3))

    def is_leader(self, duty: Duty, round_num: int, peer: int) -> bool:
        """Deterministic leader election function"""
        return (duty.slot + duty.type + round_num) % self.nodes == peer
