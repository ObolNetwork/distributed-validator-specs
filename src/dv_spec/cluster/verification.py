"""Verifying that a lock's signatures attest to the lock a node is holding.

A node MUST verify these before running with a lock file. The lock hash is the
only thing binding the definition the operators signed to the keys the DKG
produced, so a lock whose signatures do not cover the content it carries is a
lock some other cluster agreed to.

Two independent attestations exist, and they prove different things:

- `signature_aggregate` is a plain BLS aggregate over the lock hash, signed by
  every private key share of every validator. Because the shares are the DKG's
  output, this proves the ceremony participants agreed on this lock.
- `node_signatures` are secp256k1 signatures of the lock hash by each operator's
  charon node key. This proves each *node* — not just each key share — accepted
  the lock, which is what makes an operator accountable for it.

Note that the aggregate is a plain aggregate, not a threshold aggregate: it is
verified against the concatenated public shares rather than against the group
public keys. `docs/dv-spec/sigagg.md` covers why the two aggregations differ.

Scope
-----
- Verifying the two signature sets and the public share structure of a lock.

Out of scope
------------
- ENR decoding, so `verify_node_signatures` takes each node's public key rather
  than reading it out of the operator's ENR.
- The definition's EIP-712 operator signatures, which are Ethereum signatures
  over the config hash and need an EIP-712 domain rather than a DV wire format.
- Deposit data and builder registration signatures, which are beacon chain
  domain-separated.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

from dv_spec.cluster.hashing import lock_hash
from dv_spec.cluster.lock import DistValidator, Lock
from dv_spec.crypto import bls, secp256k1


def aggregate_pubkeys(validators: Iterable[DistValidator]) -> List[bytes]:
    """Return every public share of every validator, in file order.

    This is the public key set the lock's `signature_aggregate` verifies against:
    one signature per share per validator, plainly aggregated.
    """
    return [pubshare for validator in validators for pubshare in validator.pubshares]


def verify_pubshare_counts(lock: Lock) -> None:
    """Check every validator carries exactly one public share per operator.

    Also rejects repeats: a group public key appearing twice, or one validator
    carrying the same public share at two positions. Charon rejects both, and a
    duplicated share is not always caught by reconstruction — a polynomial can
    legitimately take the same value at two points.

    Raises:
        ValueError: If any validator's share count differs from the number of
            operators, if two validators share a group public key, or if a
            validator repeats a public share.
    """
    expected = lock.definition.num_operators

    seen: set[bytes] = set()
    for index, validator in enumerate(lock.validators):
        if len(validator.pubshares) != expected:
            raise ValueError(
                f"validator {index} has {len(validator.pubshares)} public shares, "
                f"expected one per operator ({expected})"
            )

        if validator.pubkey in seen:
            raise ValueError(f"validator {index} repeats an earlier group public key")

        seen.add(validator.pubkey)

        if len(set(validator.pubshares)) != len(validator.pubshares):
            raise ValueError(f"validator {index} repeats a public share")


def verify_shares_reconstruct(lock: Lock) -> None:
    """Check each validator's public shares lie on its group key's polynomial.

    Charon recovers the group public key from the first `threshold` shares, then
    re-recovers it once per remaining share, substituting that share for one of
    the first. Checking only the first quorum would leave a corrupted extra share
    undetected until that node's partial signatures started failing.

    Raises:
        ValueError: If the threshold is out of range, or any share does not
            reconstruct the group public key.
    """
    threshold = lock.threshold

    for index, validator in enumerate(lock.validators):
        shares = validator.pubshares
        if threshold < 1 or threshold > len(shares):
            raise ValueError(
                f"validator {index} has threshold {threshold} for {len(shares)} shares"
            )

        quorum = {position + 1: shares[position] for position in range(threshold)}
        if bls.recover_pubkey(quorum) != validator.pubkey:
            raise ValueError(
                f"validator {index}: public shares do not reconstruct the group public key"
            )

        for position in range(threshold, len(shares)):
            substituted = {place + 1: shares[place] for place in range(threshold - 1)}
            substituted[position + 1] = shares[position]
            if bls.recover_pubkey(substituted) != validator.pubkey:
                raise ValueError(
                    f"validator {index}: share {position + 1} does not lie on the "
                    "group key's polynomial"
                )


def verify_signature_aggregate(lock: Lock) -> bool:
    """Return whether the lock's BLS aggregate signs its own lock hash.

    The aggregate is verified against every public share of every validator, in
    file order, because it aggregates one signature per share.
    """
    return bls.verify_aggregate(
        aggregate_pubkeys(lock.validators),
        lock_hash(lock),
        lock.signature_aggregate,
    )


def verify_node_signatures(lock: Lock, node_pubkeys: Sequence[bytes]) -> bool:
    """Return whether every operator's node signature signs the lock hash.

    The hash is recomputed from the lock's content rather than read from its
    `lock_hash` field. Charon verifies against the stored field, which is safe
    only because it verifies the hashes first — under `--no-verify` it will
    check node signatures against whatever hash the file claims. Recomputing
    closes that gap and assumes nothing about call order.

    Args:
        lock: The lock to verify.
        node_pubkeys: The secp256k1 public key of each operator's charon node, in
            operator order. Charon reads these from the operators' ENRs, which
            this spec does not decode.

    Returns:
        True if there is one valid signature per operator. A lock with no
        operators passes vacuously, as it does in Charon; rejecting an empty
        lock is `verify_signature_aggregate`'s job.

    Raises:
        ValueError: If the number of signatures or public keys does not match the
            number of operators. A count mismatch is a malformed file rather than
            a failed signature, so it is not reported as `False`.
    """
    operators = lock.definition.num_operators
    if len(lock.node_signatures) != operators:
        raise ValueError(
            f"lock has {len(lock.node_signatures)} node signatures for {operators} operators"
        )

    if len(node_pubkeys) != operators:
        raise ValueError(f"got {len(node_pubkeys)} node public keys for {operators} operators")

    digest = lock_hash(lock)

    return all(
        secp256k1.verify(pubkey, digest, signature)
        for pubkey, signature in zip(node_pubkeys, lock.node_signatures, strict=True)
    )
