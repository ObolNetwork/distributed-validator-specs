"""SSZ merkleization, as Charon applies it.

Charon merkleizes in two rather different ways, and both live here because they
share a tree construction.

The wire path hashes a protobuf message by merkleizing its deterministic
encoding as a list of 32-byte chunks (`hashProto`, identical in
`core/consensus/qbft` and `core/priority`). The result is what QBFT signatures
cover, what `value_hash` holds, and what the priority protocol groups topics and
priorities by. Two properties of it are surprising and load-bearing for interop,
so they are called out here rather than left implicit:

- There is no length mixin. The tree is sized to the chunk count, so encodings
  that differ only in trailing zero bytes hash identically. This is safe only
  because the input is a canonical protobuf encoding, in which trailing zeros
  cannot vary.
- An encoding of 32 bytes or fewer is **not hashed at all**: the result is the
  encoding right-padded with zeros. A `Duty{slot: 1, type: 2}` therefore
  "hashes" to `0x0801100200...00`, and an empty message to 32 zero bytes.

The cluster configuration path is proper SSZ: Charon walks a `Definition` or
`Lock` field by field through the `HashWalker` interface of its SSZ library
(`cluster/ssz.go`), and every list carries an explicit capacity and a length
mixin. `HashWalker` below is that interface. It is a faithful reimplementation
rather than a general SSZ library: it offers exactly the operations
`cluster/ssz.go` performs, so a reader can follow the two side by side.

Scope
-----
- The zero-hash table, chunking, merkleization with or without a capacity
  limit, `hash_proto`, and the incremental `HashWalker`.

Out of scope
------------
- SSZ *serialization* (as opposed to hashing) of any type, and the beacon-chain
  types themselves. Neither appears on a DV wire path or in a cluster file.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, List

CHUNK_SIZE = 32
"""Size in bytes of an SSZ leaf chunk."""

UINT64_SIZE = 8
"""Size in bytes of an SSZ uint64, before it is padded into a chunk."""

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


def calculate_limit(max_capacity: int, num_items: int, item_size: int) -> int:
    """Return the chunk capacity of a list of fixed-size items.

    Args:
        max_capacity: Maximum number of items the list may hold.
        num_items: Number of items actually present.
        item_size: Serialized size of one item, in bytes.

    Returns:
        The number of leaves the tree must be sized for. A declared capacity of
        zero falls back to the number of items present, or one for an empty
        list, so that the tree always has at least one leaf.
    """
    limit = (max_capacity * item_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    if limit:
        return limit

    return num_items or 1


def merkleize(chunks: List[bytes], limit: int = 0) -> bytes:
    """Merkleize chunks into a single root, with no length mixin.

    Levels with an odd number of nodes are completed with that level's
    zero-subtree hash rather than a zero leaf.

    Args:
        chunks: The 32-byte leaves.
        limit: Number of leaves the tree is sized for, which fixes its depth
            independently of how many chunks are present. Zero means "size the
            tree to the chunks present", which is what the wire path uses.

    Returns:
        The 32-byte root. A single chunk in a single-leaf tree is its own root,
        and no chunks at all give the zero chunk or the zero subtree of the
        tree's depth.

    Raises:
        ValueError: If there are more chunks than the limit allows.
    """
    count = len(chunks)
    if limit == 0:
        limit = count
    elif count > limit:
        raise ValueError(f"{count} chunks exceed the limit of {limit}")

    if limit == 0:
        return ZERO_CHUNK

    if limit == 1:
        return chunks[0] if count == 1 else ZERO_CHUNK

    depth = chunk_count_depth(limit)
    if count == 0:
        return ZERO_HASHES[depth]

    layer = list(chunks)
    for level in range(depth):
        if len(layer) % 2:
            layer.append(ZERO_HASHES[level])

        layer = [hashlib.sha256(layer[i] + layer[i + 1]).digest() for i in range(0, len(layer), 2)]

    return layer[0]


def _uint64_bytes(value: int) -> bytes:
    """Encode a uint64 little-endian, raising `ValueError` when out of range."""
    if not 0 <= value < 1 << 64:
        raise ValueError(f"{value} is out of range for a uint64")

    return value.to_bytes(UINT64_SIZE, "little")


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


class HashWalker:
    """An incremental SSZ hasher over a single chunk buffer.

    Every field of an object is appended as one or more whole chunks. A nested
    container or list is built by recording the buffer position with `index`,
    appending the members, and collapsing them back to a single chunk with
    `merkleize` (for a container) or `merkleize_with_mixin` (for a list). When
    the outermost object has been collapsed the buffer holds exactly one chunk,
    which `hash_root` returns.

    This mirrors the `HashWalker` interface Charon hashes cluster files through.
    Walking an object with it rather than describing its SSZ type is what makes
    version-dependent field sets expressible: a config hash and a definition
    hash differ only in which fields the walk visits.
    """

    def __init__(self) -> None:
        """Start an empty walk."""
        self.buffer = bytearray()
        """The chunk buffer. Holds the hash root once the walk is complete."""

    def index(self) -> int:
        """Return the current buffer position, to merkleize back to later."""
        return len(self.buffer)

    def append_bytes32(self, data: bytes) -> None:
        """Append data, right-padded with zeros to a whole number of chunks.

        Empty input appends nothing at all — not an empty chunk. Charon's
        `AppendBytes32` behaves the same (its doc comment claims left-padding;
        the code right-pads, and the code is what the hashes depend on).
        """
        self.buffer += data
        remainder = len(data) % CHUNK_SIZE
        if remainder:
            self.buffer += b"\x00" * (CHUNK_SIZE - remainder)

    def fill_up_to_32(self) -> None:
        """Right-pad the buffer with zeros to a chunk boundary."""
        remainder = len(self.buffer) % CHUNK_SIZE
        if remainder:
            self.buffer += b"\x00" * (CHUNK_SIZE - remainder)

    def put_bytes(self, data: bytes) -> None:
        """Append a byte string of any length, as at most a single chunk.

        One to 32 bytes are right-padded into one chunk. Anything longer is
        merkleized, so a 48-byte BLS public key contributes
        `sha256(bytes[0:32] || bytes[32:48] padded)` rather than two chunks.
        Empty input appends *nothing* — not a zero chunk — so a container
        holding an empty field has one chunk fewer, exactly as in Charon.
        """
        if len(data) <= CHUNK_SIZE:
            self.append_bytes32(data)
            return

        start = self.index()
        self.append_bytes32(data)
        self.merkleize(start)

    def put_uint64(self, value: int) -> None:
        """Append a little-endian uint64, right-padded into one chunk.

        Raises:
            ValueError: If `value` does not fit a uint64. Note Charon never
                raises here: its signed fields are cast with `uint64(...)`, so
                a negative value wraps two's-complement instead of failing.
        """
        self.append_bytes32(_uint64_bytes(value))

    def put_bool(self, value: bool) -> None:
        """Append a boolean as one chunk: `0x01` or `0x00`, then zeros."""
        self.append_bytes32(b"\x01" if value else b"\x00")

    def put_uint64_array(self, values: Iterable[int], max_capacity: int) -> None:
        """Append a uint64 list as one chunk, with its length mixed in.

        Args:
            values: The uint64 elements.
            max_capacity: Maximum number of elements the list may hold.
        """
        start = self.index()

        count = 0
        for value in values:
            self.buffer += _uint64_bytes(value)
            count += 1

        self.fill_up_to_32()
        self.merkleize_with_mixin(start, count, calculate_limit(max_capacity, count, UINT64_SIZE))

    def merkleize(self, start: int) -> None:
        """Replace everything appended since `start` with its hash root.

        This is how a container is closed: its fields become its root.
        """
        root = merkleize(self._chunks_from(start))
        del self.buffer[start:]
        self.buffer += root

    def merkleize_with_mixin(self, start: int, num: int, limit: int) -> None:
        """Replace everything since `start` with its root, length mixed in.

        This is how a list is closed, and the mixin is what distinguishes a list
        from a container: the tree is sized to `limit` leaves regardless of how
        many elements are present, then its root is hashed together with the
        element count. Without the count, a list of two empty elements and a
        list of three would collide.

        Args:
            start: Buffer position the list's elements begin at.
            num: Number of elements present, which is the value mixed in.
            limit: Number of leaves the tree is sized for.
        """
        self.fill_up_to_32()
        root = merkleize(self._chunks_from(start), limit)
        mixin = num.to_bytes(UINT64_SIZE, "little").ljust(CHUNK_SIZE, b"\x00")
        del self.buffer[start:]
        self.buffer += hashlib.sha256(root + mixin).digest()

    def hash_root(self) -> bytes:
        """Return the hash root, once the walk has collapsed to one chunk.

        Raises:
            ValueError: If the buffer does not hold exactly one chunk, which
                means the walk is unbalanced — a container or list was left
                open, or one was closed too many times.
        """
        if len(self.buffer) != CHUNK_SIZE:
            raise ValueError(f"incomplete walk: {len(self.buffer)} bytes buffered, expected 32")

        return bytes(self.buffer)

    def _chunks_from(self, start: int) -> List[bytes]:
        """Return the buffer from `start` split into whole chunks.

        Raises:
            ValueError: If that region is not chunk aligned. Every append leaves
                the buffer aligned, so this can only fire if a caller appends to
                `buffer` directly without padding — Charon's SSZ library would
                silently drop the partial chunk instead.
        """
        data = bytes(self.buffer[start:])
        if len(data) % CHUNK_SIZE:
            raise ValueError(f"buffer is not chunk aligned: {len(data)} bytes since {start}")

        return [data[i : i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]


def put_byte_list(walker: HashWalker, data: bytes, max_bytes: int, field: str) -> None:
    """Append a variable-length byte string as SSZ `ByteList[max_bytes]`.

    Args:
        walker: The walker to append to.
        data: The bytes, which may be empty.
        max_bytes: Declared maximum length. Note this bounds *bytes*, while the
            tree is sized in chunks, so the capacity is `max_bytes` rounded up.
        field: Field name, used only in the error message.

    Raises:
        ValueError: If `data` is longer than `max_bytes`.
    """
    if len(data) > max_bytes:
        raise ValueError(f"{field} is {len(data)} bytes, over the {max_bytes} byte limit")

    start = walker.index()
    walker.append_bytes32(data)
    walker.merkleize_with_mixin(start, len(data), (max_bytes + CHUNK_SIZE - 1) // CHUNK_SIZE)


def put_bytes_n(walker: HashWalker, data: bytes, size: int, field: str) -> None:
    """Append a fixed-size byte vector as SSZ `BytesN`.

    Short values are left-padded to `size`, matching Charon. Nothing in a
    cluster file is legitimately short, so this padding is a compatibility
    behaviour rather than an invariant to rely on.

    Args:
        walker: The walker to append to.
        data: The bytes, at most `size` long.
        size: The vector's fixed length.
        field: Field name, used only in the error message.

    Raises:
        ValueError: If `data` is longer than `size`.
    """
    if len(data) > size:
        raise ValueError(f"{field} is {len(data)} bytes, over the fixed length of {size}")

    walker.put_bytes(data.rjust(size, b"\x00"))
