"""SSZ merkleization of protobuf bytes.

Charon hashes a protobuf message by merkleizing its deterministic encoding as a
list of 32-byte chunks (`hashProto`, identical in `core/consensus/qbft` and
`core/priority`). The result is what QBFT signatures cover, what `value_hash`
holds, and what the priority protocol groups topics and priorities by.

Two properties of this construction are surprising and are load-bearing for
interop, so they are called out here rather than left implicit:

- There is no length mixin. The tree is sized to the chunk count, so encodings
  that differ only in trailing zero bytes hash identically. This is safe only
  because the input is a canonical protobuf encoding, in which trailing zeros
  cannot vary.
- An encoding of 32 bytes or fewer is **not hashed at all**: the result is the
  encoding right-padded with zeros. A `Duty{slot: 1, type: 2}` therefore
  "hashes" to `0x0801100200...00`, and an empty message to 32 zero bytes.

Scope
-----
- The zero-hash table, chunking, merkleization and `hash_proto`.

Out of scope
------------
- SSZ serialization of beacon-chain types, and merkleization with a length
  mixin or an explicit limit. Neither appears on any DV wire path.
"""

from __future__ import annotations

import hashlib
from typing import List

CHUNK_SIZE = 32
"""Size in bytes of an SSZ leaf chunk."""

MAX_DEPTH = 64
"""Number of zero-hash levels precomputed, matching Charon's SSZ library."""

ZERO_CHUNK = b"\x00" * CHUNK_SIZE
"""The zero leaf, and the hash of an empty message."""


def _zero_hashes() -> List[bytes]:
    """Build the zero-subtree hash for each level, bottom up."""
    hashes = [ZERO_CHUNK]
    for _ in range(MAX_DEPTH):
        hashes.append(hashlib.sha256(hashes[-1] * 2).digest())

    return hashes


ZERO_HASHES = _zero_hashes()
"""Zero-subtree hashes: `ZERO_HASHES[i]` is the root of a zero subtree of depth i."""


def chunk_count_depth(chunk_count: int) -> int:
    """Return the tree depth needed to hold `chunk_count` leaves."""
    if chunk_count <= 1:
        return 0

    return (1 << (chunk_count - 1).bit_length()).bit_length() - 1


def chunkify(data: bytes) -> List[bytes]:
    """Split bytes into 32-byte chunks, right-padding the last one with zeros."""
    remainder = len(data) % CHUNK_SIZE
    if remainder:
        data += b"\x00" * (CHUNK_SIZE - remainder)

    return [data[i : i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]


def merkleize(chunks: List[bytes]) -> bytes:
    """Merkleize chunks into a single root, with no length mixin.

    The tree is sized to the chunk count rounded up to a power of two. Levels
    with an odd number of nodes are completed with that level's zero-subtree
    hash rather than a zero leaf.

    Args:
        chunks: The 32-byte leaves.

    Returns:
        The 32-byte root. A single chunk is its own root, and no chunks at all
        give the zero chunk.
    """
    if not chunks:
        return ZERO_CHUNK

    if len(chunks) == 1:
        return chunks[0]

    layer = list(chunks)
    for level in range(chunk_count_depth(len(chunks))):
        if len(layer) % 2:
            layer.append(ZERO_HASHES[level])

        layer = [hashlib.sha256(layer[i] + layer[i + 1]).digest() for i in range(0, len(layer), 2)]

    return layer[0]


def hash_proto(encoding: bytes) -> bytes:
    """Return the SSZ hash root of a deterministic protobuf encoding.

    Args:
        encoding: The message's deterministic protobuf encoding, as produced by
            `dv_spec.encoding.proto`.

    Returns:
        The 32-byte root. Note that encodings of 32 bytes or fewer are returned
        zero-padded rather than hashed; see the module docstring.
    """
    if len(encoding) <= CHUNK_SIZE:
        return chunkify(encoding)[0] if encoding else ZERO_CHUNK

    return merkleize(chunkify(encoding))
