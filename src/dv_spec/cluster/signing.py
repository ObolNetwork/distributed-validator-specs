"""Beacon chain signing domains and signing roots for cluster file signatures.

A lock carries two kinds of signature made by each validator's group key at DKG
time: the deposit data that funds the validator, and the builder registration
that lets it use the builder network. Both are ordinary Ethereum signatures over
a *signing root*, which binds the signed object to a domain:

```text
fork_data_root = hash_tree_root(ForkData(current_version, genesis_validators_root))
domain         = domain_type || fork_data_root[:28]
signing_root   = hash_tree_root(SigningData(object_root, domain))
```

Both domains are computed with the definition's `fork_version` and an **all-zero
genesis validators root**, as the consensus specs require for deposits
(`compute_domain(DOMAIN_DEPOSIT)`, so a deposit is valid before genesis) and the
builder specs for registrations (`DOMAIN_APPLICATION_BUILDER`). A cluster
definition's fork version is the network's genesis fork version, which is what
both call for.

Scope
-----
- `compute_domain`, `compute_signing_root`, and the deposit and registration
  signing roots of a lock's pre-generated signatures.

Out of scope
------------
- Domains that need a genesis validators root, which a cluster file does not
  carry; duty signing roots are the validator API's concern.
"""

from __future__ import annotations

import hashlib

from dv_spec.encoding.ssz import HashWalker, put_bytes_n

DOMAIN_DEPOSIT = bytes.fromhex("03000000")
"""`DOMAIN_DEPOSIT` from the phase0 consensus spec."""

DOMAIN_APPLICATION_BUILDER = bytes.fromhex("00000001")
"""`DOMAIN_APPLICATION_BUILDER` from the builder spec."""

ZERO_ROOT = bytes(32)
"""The genesis validators root both cluster file domains are computed with."""

DOMAIN_TYPE_LENGTH = 4
"""Length of a domain type."""

FORK_VERSION_LENGTH = 4
"""Length of a fork version."""

ROOT_LENGTH = 32
"""Length of a hash tree root, and of a domain."""


def compute_fork_data_root(fork_version: bytes, genesis_validators_root: bytes) -> bytes:
    """Return `hash_tree_root(ForkData(fork_version, genesis_validators_root))`.

    Raises:
        ValueError: If either input has the wrong length.
    """
    walker = HashWalker()
    start = walker.index()
    put_bytes_n(walker, fork_version, FORK_VERSION_LENGTH, "fork_version")
    put_bytes_n(walker, genesis_validators_root, ROOT_LENGTH, "genesis_validators_root")
    walker.merkleize(start)

    return walker.hash_root()


def compute_domain(
    domain_type: bytes, fork_version: bytes, genesis_validators_root: bytes = ZERO_ROOT
) -> bytes:
    """Return the 32-byte signing domain, as the consensus spec's `compute_domain`.

    Raises:
        ValueError: If any input has the wrong length.
    """
    if len(domain_type) != DOMAIN_TYPE_LENGTH:
        raise ValueError(f"domain type has the wrong length: {len(domain_type)} bytes")

    fork_data_root = compute_fork_data_root(fork_version, genesis_validators_root)

    return domain_type + fork_data_root[: ROOT_LENGTH - DOMAIN_TYPE_LENGTH]


def compute_signing_root(object_root: bytes, domain: bytes) -> bytes:
    """Return `hash_tree_root(SigningData(object_root, domain))`.

    Both members are 32 bytes, so the container is a single hash of the two.

    Raises:
        ValueError: If either input is not 32 bytes.
    """
    if len(object_root) != ROOT_LENGTH or len(domain) != ROOT_LENGTH:
        raise ValueError("object root and domain must both be 32 bytes")

    return hashlib.sha256(object_root + domain).digest()
