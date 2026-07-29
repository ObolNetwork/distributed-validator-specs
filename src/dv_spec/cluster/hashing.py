"""Config, definition and lock hashes for cluster files at v1.10.0.

Three hashes are derived from a cluster's configuration, and they differ only in
which fields the walk visits:

- The **config hash** covers the configuration the operators agree on, excluding
  every field they cannot know in advance: operator ENRs and all signatures. It
  has to be stable while signatures are being collected, which is the whole
  reason it exists.
- The **definition hash** covers the same fields plus the ENRs, the signatures,
  and the config hash itself. It identifies a fully signed definition.
- The **lock hash** covers the definition hash's fields plus the distributed
  validators the DKG produced. It is what the lock's BLS aggregate and the
  operators' node signatures sign, and it is *not* covered by itself.

All three are SSZ hash roots produced by walking the object field by field
through `encoding.ssz.HashWalker`, mirroring Charon's `cluster/ssz.go`.

Only v1.10.0 is implemented, per the decision to target v1.10 while Charon moves
to v1.11. For orientation, the neighbouring versions differ as follows: v1.9 has
no `target_gas_limit` or `compounding` field, and v1.11 turns operator and creator
signatures into lists of 65-byte signatures (`List[Bytes65, 32]`) to support Safe
smart-contract multisigs, which changes every hash in the file.

Scope
-----
- `config_hash`, `definition_hash` and `lock_hash` at v1.10.0, and the
  verification of hashes stored in a file against recomputation.

Out of scope
------------
- Versions other than v1.10.0.
- Signature verification, which is in `verification.py`.
"""

from __future__ import annotations

from dv_spec.cluster.definition import (
    ADDRESS_LENGTH,
    FORK_VERSION_LENGTH,
    HASH_LENGTH,
    K1_SIGNATURE_LENGTH,
    MAX_DEPOSIT_AMOUNTS,
    MAX_DKG_ALGORITHM_BYTES,
    MAX_ENR_BYTES,
    MAX_NAME_BYTES,
    MAX_OPERATORS,
    MAX_TIMESTAMP_BYTES,
    MAX_UUID_BYTES,
    MAX_VALIDATORS,
    MAX_VERSION_BYTES,
    Definition,
    require_supported_version,
)
from dv_spec.cluster.lock import (
    BLS_SIGNATURE_LENGTH,
    PUBKEY_LENGTH,
    WITHDRAWAL_CREDENTIALS_LENGTH,
    BuilderRegistration,
    DepositData,
    DistValidator,
    Lock,
    Registration,
)
from dv_spec.encoding.ssz import HashWalker, put_byte_list, put_bytes_n
from dv_spec.types.hex import decode_hex_bytes


def decode_address(address: str) -> bytes:
    """Decode a hex Ethereum address to bytes.

    An empty string decodes to no bytes at all rather than to zeros, and the
    caller left-pads it to 20 bytes. Charon does the same, so an absent address
    and an all-zero address hash identically.

    Args:
        address: A 20-byte address as a hex string, with or without `0x`, or the
            empty string.

    Returns:
        The decoded bytes, empty if `address` was empty.

    Raises:
        ValueError: If the string is not valid hex, or decodes to a length other
            than 20 bytes.
    """
    if not address:
        return b""

    try:
        raw: bytes = decode_hex_bytes(address)
    except ValueError as exc:
        raise ValueError(f"invalid address {address!r}: {exc}") from exc

    if len(raw) != ADDRESS_LENGTH:
        raise ValueError(
            f"address {address!r} decodes to {len(raw)} bytes, expected {ADDRESS_LENGTH}"
        )

    return raw


def put_address(walker: HashWalker, address: str, field: str) -> None:
    """Append a hex Ethereum address as SSZ `Bytes20`."""
    put_bytes_n(walker, decode_address(address), ADDRESS_LENGTH, field)


def hash_definition_v1x10(walker: HashWalker, definition: Definition, *, config_only: bool) -> None:
    """Walk a v1.10.0 definition, leaving its hash root as one chunk.

    Args:
        walker: The walker to append to.
        definition: The definition to hash.
        config_only: Visit only the fields the config hash covers, skipping
            operator ENRs, all signatures, and the stored config hash.
    """
    start = walker.index()

    put_byte_list(walker, definition.uuid.encode(), MAX_UUID_BYTES, "uuid")
    put_byte_list(walker, definition.name.encode(), MAX_NAME_BYTES, "name")
    put_byte_list(walker, definition.version.encode(), MAX_VERSION_BYTES, "version")
    put_byte_list(walker, definition.timestamp.encode(), MAX_TIMESTAMP_BYTES, "timestamp")
    walker.put_uint64(definition.num_validators)
    walker.put_uint64(definition.threshold)
    put_byte_list(
        walker, definition.dkg_algorithm.encode(), MAX_DKG_ALGORITHM_BYTES, "dkg_algorithm"
    )
    put_bytes_n(walker, definition.fork_version, FORK_VERSION_LENGTH, "fork_version")

    operators_start = walker.index()
    for operator in definition.operators:
        operator_start = walker.index()
        put_address(walker, operator.address, "operator address")
        if not config_only:
            put_byte_list(walker, operator.enr.encode(), MAX_ENR_BYTES, "enr")
            put_bytes_n(walker, operator.config_signature, K1_SIGNATURE_LENGTH, "config_signature")
            put_bytes_n(walker, operator.enr_signature, K1_SIGNATURE_LENGTH, "enr_signature")

        walker.merkleize(operator_start)

    walker.merkleize_with_mixin(operators_start, len(definition.operators), MAX_OPERATORS)

    creator_start = walker.index()
    put_address(walker, definition.creator.address, "creator address")
    if not config_only:
        put_bytes_n(
            walker,
            definition.creator.config_signature,
            K1_SIGNATURE_LENGTH,
            "creator config_signature",
        )

    walker.merkleize(creator_start)

    addresses_start = walker.index()
    for addresses in definition.validator_addresses:
        address_start = walker.index()
        put_address(walker, addresses.fee_recipient_address, "fee_recipient_address")
        put_address(walker, addresses.withdrawal_address, "withdrawal_address")
        walker.merkleize(address_start)

    walker.merkleize_with_mixin(
        addresses_start, len(definition.validator_addresses), MAX_VALIDATORS
    )

    walker.put_uint64_array(definition.deposit_amounts, MAX_DEPOSIT_AMOUNTS)
    put_byte_list(
        walker, definition.consensus_protocol.encode(), MAX_NAME_BYTES, "consensus_protocol"
    )
    walker.put_uint64(definition.target_gas_limit)
    walker.put_bool(definition.compounding)

    if not config_only:
        put_bytes_n(walker, definition.config_hash, HASH_LENGTH, "config_hash")

    walker.merkleize(start)


def hash_deposit_data(walker: HashWalker, deposit: DepositData) -> None:
    """Walk deposit data, leaving its hash root as one chunk."""
    start = walker.index()
    put_bytes_n(walker, deposit.pubkey, PUBKEY_LENGTH, "deposit pubkey")
    put_bytes_n(
        walker,
        deposit.withdrawal_credentials,
        WITHDRAWAL_CREDENTIALS_LENGTH,
        "withdrawal_credentials",
    )
    walker.put_uint64(deposit.amount)
    put_bytes_n(walker, deposit.signature, BLS_SIGNATURE_LENGTH, "deposit signature")
    walker.merkleize(start)


def hash_registration(walker: HashWalker, registration: Registration) -> None:
    """Walk a builder registration message, leaving its hash root as one chunk."""
    start = walker.index()
    # Charon appends the fee recipient without a fixed length, so unlike every
    # other address in a cluster file a short value is right-padded, not left.
    walker.put_bytes(registration.fee_recipient)
    walker.put_uint64(registration.gas_limit)
    walker.put_uint64(registration.timestamp)
    put_bytes_n(walker, registration.pubkey, PUBKEY_LENGTH, "registration pubkey")
    walker.merkleize(start)


def hash_builder_registration(walker: HashWalker, registration: BuilderRegistration) -> None:
    """Walk a signed builder registration, leaving its hash root as one chunk."""
    start = walker.index()
    hash_registration(walker, registration.message)
    put_bytes_n(walker, registration.signature, BLS_SIGNATURE_LENGTH, "registration signature")
    walker.merkleize(start)


def hash_validator_v1x8_or_later(walker: HashWalker, validator: DistValidator) -> None:
    """Walk a distributed validator, leaving its hash root as one chunk.

    v1.8 replaced v1.5's single deposit data with a list of partial deposits, so
    a validator funded by one full deposit still hashes as a one-element list.
    """
    start = walker.index()
    put_bytes_n(walker, validator.pubkey, PUBKEY_LENGTH, "validator pubkey")

    shares_start = walker.index()
    for pubshare in validator.pubshares:
        put_bytes_n(walker, pubshare, PUBKEY_LENGTH, "pubshare")

    walker.merkleize_with_mixin(shares_start, len(validator.pubshares), MAX_OPERATORS)

    deposits_start = walker.index()
    for deposit in validator.partial_deposit_data:
        # The deposit hash is already a single chunk, so this closes a container
        # of one member and leaves the chunk untouched. Charon does it too.
        deposit_start = walker.index()
        hash_deposit_data(walker, deposit)
        walker.merkleize(deposit_start)

    walker.merkleize_with_mixin(
        deposits_start, len(validator.partial_deposit_data), MAX_DEPOSIT_AMOUNTS
    )

    hash_builder_registration(walker, validator.builder_registration)
    walker.merkleize(start)


def hash_lock_v1x3_or_later(walker: HashWalker, lock: Lock) -> None:
    """Walk a lock, leaving its hash root as one chunk.

    The name is Charon's, whose same-named function dispatches on version. Here
    only the v1.10 definition walk exists, and the version guard lives in
    `lock_hash`, so calling this directly does not check the version.
    """
    start = walker.index()
    hash_definition_v1x10(walker, lock.definition, config_only=False)

    validators_start = walker.index()
    for validator in lock.validators:
        hash_validator_v1x8_or_later(walker, validator)

    walker.merkleize_with_mixin(validators_start, len(lock.validators), MAX_VALIDATORS)
    walker.merkleize(start)


def config_hash(definition: Definition) -> bytes:
    """Return the config hash of a definition.

    This excludes operator ENRs and every signature, so it is unchanged by
    collecting operator signatures — which is what lets operators sign it.

    Raises:
        ValueError: If the definition's version is not supported.
    """
    require_supported_version(definition.version)

    walker = HashWalker()
    hash_definition_v1x10(walker, definition, config_only=True)

    return walker.hash_root()


def definition_hash(definition: Definition) -> bytes:
    """Return the definition hash, covering every field including the config hash.

    Raises:
        ValueError: If the definition's version is not supported.
    """
    require_supported_version(definition.version)

    walker = HashWalker()
    hash_definition_v1x10(walker, definition, config_only=False)

    return walker.hash_root()


def lock_hash(lock: Lock) -> bytes:
    """Return the lock hash, covering the definition and the validators.

    Raises:
        ValueError: If the lock's version is not supported.
    """
    require_supported_version(lock.version)

    walker = HashWalker()
    hash_lock_v1x3_or_later(walker, lock)

    return walker.hash_root()


def verify_definition_hashes(definition: Definition) -> None:
    """Check the hashes stored in a definition against recomputation.

    A reader MUST do this before trusting any field of a definition file: the
    signatures only bind the fields the hashes cover, so a stored hash that
    disagrees with the content means the signatures attest to something else.

    Raises:
        ValueError: If either stored hash does not match, naming which.
    """
    expected_config = config_hash(definition)
    if definition.config_hash != expected_config:
        raise ValueError(
            f"config hash mismatch: file has {definition.config_hash.hex()}, "
            f"content hashes to {expected_config.hex()}"
        )

    expected_definition = definition_hash(definition)
    if definition.definition_hash != expected_definition:
        raise ValueError(
            f"definition hash mismatch: file has {definition.definition_hash.hex()}, "
            f"content hashes to {expected_definition.hex()}"
        )


def verify_lock_hash(lock: Lock) -> None:
    """Check the hashes stored in a lock, including the definition's.

    Raises:
        ValueError: If any stored hash does not match its content.
    """
    verify_definition_hashes(lock.definition)

    expected = lock_hash(lock)
    if lock.lock_hash != expected:
        raise ValueError(
            f"lock hash mismatch: file has {lock.lock_hash.hex()}, "
            f"content hashes to {expected.hex()}"
        )
