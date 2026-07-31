"""Helper functions and utilities for ParSigEx protocol.

Provides verification helpers, encoding utilities, and protocol constants.
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from dv_spec.types.duty import Duty, DutyType

from .message import ParSignedData, ParSignedDataSet

# Protocol constants
PROTOCOL_ID = "/charon/parsigex/2.0.0"


def is_duty_always_accepted(duty: Duty) -> bool:
    """Check if a duty type is always accepted (no gating required).

    DutyExit and DutyBuilderRegistration are lifecycle operations that
    are always relevant.
    """
    return duty.type in {DutyType.EXIT, DutyType.BUILDER_REGISTRATION}


def make_simple_gater(expected_duties: set[Duty]) -> Callable[[Duty], bool]:
    """Create a simple duty gater function that accepts only expected duties.

    Args:
        expected_duties: Set of duties that should be accepted

    Returns:
        A gater function that returns True if the duty is accepted
    """

    def gater(duty: Duty) -> bool:
        if is_duty_always_accepted(duty):
            return True
        return duty in expected_duties

    return gater


def extract_pubkeys(data_set: ParSignedDataSet) -> list[str]:
    """Extract all validator public keys from a ParSignedDataSet.

    Args:
        data_set: The partial signature data set

    Returns:
        List of validator public key strings
    """
    return list(data_set.set.keys())


def count_shares(data_set: ParSignedDataSet) -> int:
    """Count the number of partial signatures in a data set.

    Args:
        data_set: The partial signature data set

    Returns:
        Number of partial signatures
    """
    return len(data_set.set)


def verify_peer_share_idx(
    share_idx_by_peer: Mapping[str, int],
    sender: str,
    data: ParSignedData,
) -> None:
    """Bind a received partial signature to its authenticated sender.

    A peer may only contribute partial signatures under its own assigned share
    index, so it cannot deposit a signature into another operator's slot. This is
    the same check `verify_node_sig_msg` applies to node signatures, expressed
    over share indices instead of peer indices.

    `share_idx_by_peer` is keyed by peer ID and holds each peer's *assigned*
    share index, which is not necessarily its position in the peer list. After
    operators are removed the remaining ones keep their original share indices
    (see the share index compaction rules in the cluster edit protocols), so
    deriving the expected index from peer position would reject valid signatures.

    Where this check applies:

    - The **DKG lock-hash exchange** enforces it. Signing roots are not known
      while the exchange is running, so cryptographic verification is deferred
      until aggregation and the authenticated sender is the only thing a receiver
      can check at reception time.
    - The **core workflow** does not. Those partial signatures are verified
      against the public share for the claimed share index, which already binds
      them to a share, so the sender adds nothing. A receiver that enforced the
      binding here would reject partial signatures Charon accepts.

    Args:
        share_idx_by_peer: Assigned 1-based share index per participating peer ID.
        sender: Peer ID resolved from the authenticated libp2p sender identity.
        data: The received partial signature.

    Raises:
        ValueError: If the sender is not a participating peer, or the claimed
            share index is not the one assigned to it.
    """
    expected_share_idx = share_idx_by_peer.get(sender)
    if expected_share_idx is None:
        raise ValueError("partial signature from unknown peer")

    # `ParSignedData` already constrains share_idx to >= 1, so a non-positive
    # index cannot reach here through a parsed message. Checked anyway, because
    # Charon has no such constraint on the type and folds both cases into one
    # rejection: a caller passing an unvalidated index must not slip through.
    if data.share_idx <= 0 or data.share_idx != expected_share_idx:
        raise ValueError("partial signature share index does not match sender peer")


def validate_exchange_peers(
    peers: Sequence[str],
    share_idx_by_peer: Mapping[str, int],
    peer_idx: int,
) -> None:
    """Validate an exchange's peer configuration before it starts.

    Every participating peer needs a valid assigned share index. A peer missing
    from the map has its partial signatures rejected as coming from an unknown
    peer, which does not surface as a configuration error — the exchange simply
    never reaches its threshold and times out. Failing here instead makes a
    misconfigured map immediately diagnosable.

    Args:
        peers: Participating peer IDs, ordered by peer index.
        share_idx_by_peer: Assigned 1-based share index per participating peer ID.
        peer_idx: This node's own 0-based peer index.

    Raises:
        ValueError: If `peer_idx` is out of range for `peers`, or any peer has no
            valid assigned share index.
    """
    if not 0 <= peer_idx < len(peers):
        raise ValueError("peer index out of range")

    for peer in peers:
        share_idx = share_idx_by_peer.get(peer)
        if share_idx is None or share_idx <= 0:
            raise ValueError(f"peer map missing valid share index for peer {peer}")


def validate_share_indices(data_set: ParSignedDataSet, expected_range: tuple[int, int]) -> bool:
    """Validate that all share indices are within expected range.

    Args:
        data_set: The partial signature data set
        expected_range: Tuple of (min_idx, max_idx) inclusive

    Returns:
        True if all share indices are valid
    """
    min_idx, max_idx = expected_range
    for par_sig in data_set.set.values():
        if not (min_idx <= par_sig.share_idx <= max_idx):
            return False
    return True
