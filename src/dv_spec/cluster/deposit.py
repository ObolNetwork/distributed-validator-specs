"""Deposit amounts, withdrawal credentials and deposit signing roots.

Every validator in a lock carries one or more pre-signed deposits. They are what
an operator submits to the deposit contract, so a wrong field here sends real
funds somewhere unintended: the deposit contract accepts any 32 bytes as
withdrawal credentials, so credentials with the wrong prefix or padding — or a
short value padded to 32 bytes — can leave the balance withdrawable only by
whoever holds the matching key, if anyone does. A node MUST therefore check
every deposit against the definition rather than trust that the DKG produced it
correctly (`dv_spec.cluster.verification.verify_deposit_data`).

Rules
-----
- **Amounts.** Each amount is at least 1 ETH and at most the maximum effective
  balance of its credential type: 32 ETH for `0x01` credentials, 2048 ETH for
  `0x02` (compounding, EIP-7251).
- **Sum.** A definition's non-empty `deposit_amounts` sum to at least 32 ETH,
  repetition allowed, so the deposits can activate the validator. This is
  Charon's `deposit.VerifyDepositAmounts`, which it applies when it parses a
  definition.
- **Default amounts.** A definition whose `deposit_amounts` is empty has deposits
  for Charon's default amounts: 1 ETH and 32 ETH, or 1, 8, 32 and 256 ETH when
  compounding (`deposit.DefaultDepositAmounts` in Charon, which its DKG and
  `create cluster` both use from v1.8 on).
- **Withdrawal credentials.** A validator's credentials are derived from its
  withdrawal address in the definition: the prefix byte (`0x01`, or `0x02` when
  the definition sets `compounding`), eleven zero bytes, then the 20 address
  bytes. Nothing else is accepted, so a `0x00` (BLS) prefix, a bare address, or
  non-zero padding are all rejected.

Scope
-----
- The amount bounds and defaults, credential derivation, and the deposit
  message root and signing root.

Out of scope
------------
- The deposit contract and `deposit_data_root`, which a lock does not carry.
"""

from __future__ import annotations

from typing import Sequence, Tuple

from dv_spec.cluster.signing import DOMAIN_DEPOSIT, compute_domain, compute_signing_root
from dv_spec.encoding.ssz import HashWalker, put_bytes_n
from dv_spec.types.address import decode_address

GWEI_PER_ETH = 10**9
"""Gwei in one ether."""

MIN_DEPOSIT_AMOUNT = 1 * GWEI_PER_ETH
"""Smallest amount a single deposit may carry, in Gwei."""

MAX_STANDARD_DEPOSIT_AMOUNT = 32 * GWEI_PER_ETH
"""Largest single deposit for `0x01` credentials, in Gwei."""

MAX_COMPOUNDING_DEPOSIT_AMOUNT = 2048 * GWEI_PER_ETH
"""Largest single deposit for `0x02` compounding credentials, in Gwei."""

MIN_DEPOSIT_AMOUNTS_SUM = 32 * GWEI_PER_ETH
"""Smallest total a definition's non-empty deposit amounts may sum to, in Gwei."""

DEFAULT_DEPOSIT_AMOUNTS: Tuple[int, ...] = (1 * GWEI_PER_ETH, 32 * GWEI_PER_ETH)
"""Deposit amounts used when a non-compounding definition lists none."""

DEFAULT_COMPOUNDING_DEPOSIT_AMOUNTS: Tuple[int, ...] = (
    1 * GWEI_PER_ETH,
    8 * GWEI_PER_ETH,
    32 * GWEI_PER_ETH,
    256 * GWEI_PER_ETH,
)
"""Deposit amounts used when a compounding definition lists none."""

ETH1_ADDRESS_WITHDRAWAL_PREFIX = b"\x01"
"""Credential prefix of a validator withdrawing to an execution address."""

COMPOUNDING_WITHDRAWAL_PREFIX = b"\x02"
"""Credential prefix of a compounding validator (EIP-7251)."""

PUBKEY_LENGTH = 48
"""Length of a BLS public key."""

WITHDRAWAL_CREDENTIALS_LENGTH = 32
"""Length of withdrawal credentials."""


def max_deposit_amount(compounding: bool) -> int:
    """Return the largest single deposit for the credential type, in Gwei."""
    return MAX_COMPOUNDING_DEPOSIT_AMOUNT if compounding else MAX_STANDARD_DEPOSIT_AMOUNT


def default_deposit_amounts(compounding: bool) -> Tuple[int, ...]:
    """Return the amounts a definition with no `deposit_amounts` deposits."""
    return DEFAULT_COMPOUNDING_DEPOSIT_AMOUNTS if compounding else DEFAULT_DEPOSIT_AMOUNTS


def check_deposit_amount(amount: int, compounding: bool) -> None:
    """Check one deposit amount against its credential type's bounds.

    Raises:
        ValueError: If the amount is below 1 ETH or above the maximum
            ("deposit amount out of range").
    """
    maximum = max_deposit_amount(compounding)
    if not MIN_DEPOSIT_AMOUNT <= amount <= maximum:
        raise ValueError(
            f"deposit amount out of range: {amount} Gwei, expected between "
            f"{MIN_DEPOSIT_AMOUNT} and {maximum}"
        )


def check_deposit_amounts(amounts: Sequence[int], compounding: bool) -> None:
    """Check a definition's deposit amounts: each within bounds, and their sum.

    An empty list means the default amounts and is always valid. Otherwise each
    amount is checked first, then the sum, matching the order of Charon's
    `VerifyDepositAmounts`.

    Raises:
        ValueError: If an amount is out of range ("deposit amount out of
            range"), or the amounts sum to less than 32 ETH ("deposit amounts
            sum to less than 32 ETH").
    """
    if not amounts:
        return

    for amount in amounts:
        check_deposit_amount(amount, compounding)

    total = sum(amounts)
    if total < MIN_DEPOSIT_AMOUNTS_SUM:
        raise ValueError(
            f"deposit amounts sum to less than 32 ETH: {total} Gwei, "
            f"expected at least {MIN_DEPOSIT_AMOUNTS_SUM}"
        )


def withdrawal_credentials(withdrawal_address: str, compounding: bool) -> bytes:
    """Derive a validator's withdrawal credentials from its withdrawal address.

    Returns:
        `prefix || 0x00 * 11 || address`, where the prefix is `0x02` when
        `compounding` and `0x01` otherwise.

    Raises:
        ValueError: If the address is malformed.
    """
    prefix = COMPOUNDING_WITHDRAWAL_PREFIX if compounding else ETH1_ADDRESS_WITHDRAWAL_PREFIX

    return prefix + bytes(11) + decode_address(withdrawal_address)


def deposit_message_root(pubkey: bytes, credentials: bytes, amount: int) -> bytes:
    """Return `hash_tree_root(DepositMessage(pubkey, credentials, amount))`.

    Raises:
        ValueError: If the public key or credentials have the wrong length.
    """
    walker = HashWalker()
    start = walker.index()
    put_bytes_n(walker, pubkey, PUBKEY_LENGTH, "deposit pubkey")
    put_bytes_n(walker, credentials, WITHDRAWAL_CREDENTIALS_LENGTH, "withdrawal_credentials")
    walker.put_uint64(amount)
    walker.merkleize(start)

    return walker.hash_root()


def deposit_signing_root(
    pubkey: bytes, credentials: bytes, amount: int, fork_version: bytes
) -> bytes:
    """Return the root a deposit's signature is made over.

    The domain is `DOMAIN_DEPOSIT` with `fork_version` and a zero genesis
    validators root.
    """
    domain = compute_domain(DOMAIN_DEPOSIT, fork_version)

    return compute_signing_root(deposit_message_root(pubkey, credentials, amount), domain)
