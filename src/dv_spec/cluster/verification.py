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

The lock also carries signatures the group keys made at DKG time — deposit data
and builder registrations — and neither attestation above says they are right.
The aggregate proves the participants agreed on the lock, including whatever its
deposit data says; it does not prove the deposit data matches the definition.
`verify_deposit_data` and `verify_builder_registrations` check that, field by
field against the definition and then by signature.

`verify_lock` runs the whole sequence in a fixed order.

Scope
-----
- Verifying the two signature sets and the public share structure of a lock.
- Verifying each validator's deposit data and pre-generated builder
  registration against the definition and the group public key.

Out of scope
------------
- ENR decoding, so `verify_node_signatures` takes each node's public key rather
  than reading it out of the operator's ENR.
- The definition's EIP-712 operator signatures, which are Ethereum signatures
  over the config hash and need an EIP-712 domain rather than a DV wire format.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

from dv_spec.cluster.deposit import (
    check_deposit_amount,
    default_deposit_amounts,
    deposit_signing_root,
    withdrawal_credentials,
)
from dv_spec.cluster.hashing import hash_registration, lock_hash, verify_lock_hash
from dv_spec.cluster.lock import DistValidator, Lock, Registration
from dv_spec.cluster.signing import (
    DOMAIN_APPLICATION_BUILDER,
    compute_domain,
    compute_signing_root,
)
from dv_spec.crypto import bls, secp256k1
from dv_spec.encoding.ssz import HashWalker
from dv_spec.types.address import decode_address


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

    Raises:
        ValueError: If the aggregate is not 96 bytes. The lock hash does not
            cover it, so its length is checked here rather than at parse; an
            unsigned lock leaves it empty and fails here.
    """
    if len(lock.signature_aggregate) != bls.SIGNATURE_LENGTH:
        raise ValueError(
            f"signature_aggregate has the wrong length: {len(lock.signature_aggregate)} "
            f"bytes, expected {bls.SIGNATURE_LENGTH}"
        )

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
            number of operators, or a signature is not 65 bytes. A malformed file
            is not a failed signature, so it is not reported as `False`.
    """
    operators = lock.definition.num_operators
    if len(lock.node_signatures) != operators:
        raise ValueError(
            f"lock has {len(lock.node_signatures)} node signatures for {operators} operators"
        )

    if len(node_pubkeys) != operators:
        raise ValueError(f"got {len(node_pubkeys)} node public keys for {operators} operators")

    for index, signature in enumerate(lock.node_signatures):
        if len(signature) != secp256k1.SIGNATURE_LENGTH:
            raise ValueError(
                f"node signature {index} has the wrong length: {len(signature)} bytes, "
                f"expected {secp256k1.SIGNATURE_LENGTH}"
            )

    digest = lock_hash(lock)

    return all(
        secp256k1.verify(pubkey, digest, signature)
        for pubkey, signature in zip(node_pubkeys, lock.node_signatures, strict=True)
    )


def _require_one_address_entry_per_validator(lock: Lock) -> None:
    """Pair validators with the definition's address entries, or fail."""
    entries = len(lock.definition.validator_addresses)
    if len(lock.validators) != entries:
        raise ValueError(
            f"lock has {len(lock.validators)} validators but the definition has "
            f"{entries} validator address entries"
        )


def verify_deposit_data(lock: Lock) -> None:
    """Check every validator's deposit data against the definition and its key.

    Validator `i` is paired with the definition's validator address entry `i`.
    Each of its deposits is checked in this order, and the first failure is
    reported:

    1. `pubkey` equals the validator's group public key ("deposit pubkey
       mismatch").
    2. `withdrawal_credentials` equal the credentials derived from the
       validator's withdrawal address: `0x01`, or `0x02` when the definition sets
       `compounding`, then eleven zero bytes, then the address ("withdrawal
       credentials mismatch"). See `dv_spec.cluster.deposit`.
    3. `amount` is one of the definition's `deposit_amounts`, or of the default
       amounts if it lists none ("deposit amount not in definition").
    4. `amount` is within the credential type's bounds ("deposit amount out of
       range"). A valid definition makes this unreachable; it is checked so the
       rule does not depend on how the definition was built.
    5. `signature` verifies under the group public key over the deposit signing
       root, with `DOMAIN_DEPOSIT`, the definition's `fork_version` and a zero
       genesis validators root ("invalid deposit signature").

    A validator with no deposit data passes vacuously.

    Raises:
        ValueError: On the first deposit that breaks a rule, or if the number of
            validators differs from the definition's address entries.
    """
    _require_one_address_entry_per_validator(lock)

    definition = lock.definition
    allowed = set(definition.deposit_amounts) or set(
        default_deposit_amounts(definition.compounding)
    )

    for index, (validator, addresses) in enumerate(
        zip(lock.validators, definition.validator_addresses, strict=True)
    ):
        expected_credentials = withdrawal_credentials(
            addresses.withdrawal_address, definition.compounding
        )

        for position, deposit in enumerate(validator.partial_deposit_data):
            where = f"validator {index} deposit {position}"

            if deposit.pubkey != validator.pubkey:
                raise ValueError(f"deposit pubkey mismatch: {where} is for another key")

            if deposit.withdrawal_credentials != expected_credentials:
                raise ValueError(
                    f"withdrawal credentials mismatch: {where} has "
                    f"{deposit.withdrawal_credentials.hex()}, expected "
                    f"{expected_credentials.hex()}"
                )

            if deposit.amount not in allowed:
                raise ValueError(
                    f"deposit amount not in definition: {where} deposits {deposit.amount} Gwei"
                )

            check_deposit_amount(deposit.amount, definition.compounding)

            root = deposit_signing_root(
                deposit.pubkey,
                deposit.withdrawal_credentials,
                deposit.amount,
                definition.fork_version,
            )
            if not bls.verify(validator.pubkey, root, deposit.signature):
                raise ValueError(f"invalid deposit signature: {where}")


def registration_signing_root(registration: Registration, fork_version: bytes) -> bytes:
    """Return the root a builder registration's signature is made over.

    The object root is `hash_tree_root(ValidatorRegistrationV1)`, which is the
    same walk the lock hash makes of the message. The domain is
    `DOMAIN_APPLICATION_BUILDER` with `fork_version` and a zero genesis
    validators root.
    """
    walker = HashWalker()
    hash_registration(walker, registration)
    domain = compute_domain(DOMAIN_APPLICATION_BUILDER, fork_version)

    return compute_signing_root(walker.hash_root(), domain)


def verify_builder_registrations(lock: Lock) -> None:
    """Check every validator's pre-generated builder registration.

    Validator `i` is paired with the definition's validator address entry `i`,
    and its registration is checked in this order:

    1. `message.pubkey` equals the validator's group public key ("registration
       pubkey mismatch").
    2. `message.fee_recipient` equals the validator's fee recipient address in
       the definition ("registration fee recipient mismatch").
    3. `signature` verifies under the group public key over the registration
       signing root, with `DOMAIN_APPLICATION_BUILDER`, the definition's
       `fork_version` and a zero genesis validators root ("invalid registration
       signature").

    Charon verifies the signature over a message it rebuilds from the
    definition's fee recipient and the group key, not over the message the file
    carries. That accepts a file whose message names another fee recipient, as
    long as the signature is over the definition's. Comparing the carried
    message field by field and then verifying it closes that gap.

    Raises:
        ValueError: On the first registration that breaks a rule, or if the
            number of validators differs from the definition's address entries.
    """
    _require_one_address_entry_per_validator(lock)

    definition = lock.definition
    for index, (validator, addresses) in enumerate(
        zip(lock.validators, definition.validator_addresses, strict=True)
    ):
        registration = validator.builder_registration
        message = registration.message

        if message.pubkey != validator.pubkey:
            raise ValueError(f"registration pubkey mismatch: validator {index}")

        if message.fee_recipient != decode_address(addresses.fee_recipient_address):
            raise ValueError(f"registration fee recipient mismatch: validator {index}")

        root = registration_signing_root(message, definition.fork_version)
        if not bls.verify(validator.pubkey, root, registration.signature):
            raise ValueError(f"invalid registration signature: validator {index}")


def verify_lock(lock: Lock, node_pubkeys: Sequence[bytes]) -> None:
    """Run every check a node MUST make before using a lock, in order.

    1. `verify_lock_hash`: the stored config, definition and lock hashes.
    2. `verify_pubshare_counts` and `verify_shares_reconstruct`.
    3. `verify_deposit_data`.
    4. `verify_builder_registrations`.
    5. `verify_signature_aggregate`.
    6. `verify_node_signatures`.

    Parsing the lock into the models has already applied the field rules (lengths,
    addresses, deposit amounts).

    Args:
        lock: The lock to verify.
        node_pubkeys: The secp256k1 public key of each operator's charon node, in
            operator order. See `verify_node_signatures`.

    Raises:
        ValueError: On the first check that fails.
    """
    verify_lock_hash(lock)
    verify_pubshare_counts(lock)
    verify_shares_reconstruct(lock)
    verify_deposit_data(lock)
    verify_builder_registrations(lock)

    if not verify_signature_aggregate(lock):
        raise ValueError("invalid signature aggregate")

    if not verify_node_signatures(lock, node_pubkeys):
        raise ValueError("invalid node signature")
