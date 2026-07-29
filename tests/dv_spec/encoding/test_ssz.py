import hashlib

import pytest

from dv_spec.encoding.ssz import (
    ZERO_CHUNK,
    ZERO_HASHES,
    HashWalker,
    calculate_limit,
    chunk_count_depth,
    chunkify,
    hash_proto,
    merkleize,
    put_byte_list,
    put_bytes_n,
)


@pytest.mark.parametrize(
    ("chunk_count", "depth"),
    [(0, 0), (1, 0), (2, 1), (3, 2), (4, 2), (5, 3), (8, 3), (9, 4)],
)
def test_chunk_count_depth(chunk_count: int, depth: int) -> None:
    assert chunk_count_depth(chunk_count) == depth


def test_zero_hashes_are_built_from_the_level_below() -> None:
    assert ZERO_HASHES[0] == ZERO_CHUNK
    assert ZERO_HASHES[1] == hashlib.sha256(ZERO_CHUNK * 2).digest()


def test_chunkify_pads_the_final_chunk() -> None:
    assert chunkify(b"\x01") == [b"\x01" + b"\x00" * 31]
    assert chunkify(b"\xff" * 32) == [b"\xff" * 32]
    assert chunkify(b"\xff" * 33) == [b"\xff" * 32, b"\xff" + b"\x00" * 31]


def test_merkleize_edge_cases() -> None:
    assert merkleize([]) == ZERO_CHUNK
    assert merkleize([b"\x01" * 32]) == b"\x01" * 32


def test_merkleize_pairs_two_chunks() -> None:
    left, right = b"\x01" * 32, b"\x02" * 32

    assert merkleize([left, right]) == hashlib.sha256(left + right).digest()


def test_merkleize_completes_odd_layers_with_zero_subtrees() -> None:
    chunks = [bytes([i]) * 32 for i in range(3)]
    expected_left = hashlib.sha256(chunks[0] + chunks[1]).digest()
    expected_right = hashlib.sha256(chunks[2] + ZERO_HASHES[0]).digest()

    assert merkleize(chunks) == hashlib.sha256(expected_left + expected_right).digest()


def test_hash_proto_returns_short_encodings_zero_padded() -> None:
    # Charon's hasher does not hash inputs of 32 bytes or fewer at all.
    assert hash_proto(b"") == ZERO_CHUNK
    assert hash_proto(b"\x08\x01") == b"\x08\x01" + b"\x00" * 30
    assert hash_proto(b"\xff" * 32) == b"\xff" * 32


def test_hash_proto_hashes_longer_encodings() -> None:
    encoding = b"\xff" * 33
    assert hash_proto(encoding) == merkleize(chunkify(encoding))


def test_merkleize_sizes_the_tree_to_the_limit() -> None:
    # One chunk in a four-leaf tree is two levels of zero-subtree padding, not
    # the chunk itself.
    chunk = b"\x01" * 32
    level0 = hashlib.sha256(chunk + ZERO_HASHES[0]).digest()

    assert merkleize([chunk], limit=4) == hashlib.sha256(level0 + ZERO_HASHES[1]).digest()
    assert merkleize([chunk], limit=1) == chunk


def test_merkleize_empty_input_uses_the_limits_zero_subtree() -> None:
    assert merkleize([], limit=1) == ZERO_CHUNK
    assert merkleize([], limit=4) == ZERO_HASHES[2]
    assert merkleize([], limit=64) == ZERO_HASHES[6]


def test_merkleize_rejects_more_chunks_than_the_limit() -> None:
    with pytest.raises(ValueError, match="exceed the limit"):
        merkleize([ZERO_CHUNK] * 3, limit=2)


@pytest.mark.parametrize(
    ("max_capacity", "num_items", "item_size", "limit"),
    [
        (256, 2, 8, 64),  # deposit_amounts: uint64[256] spans 64 chunks
        (256, 0, 32, 256),  # a list of 32-byte roots is one chunk per item
        (0, 0, 8, 1),  # an undeclared capacity still needs one leaf
        (0, 5, 8, 5),  # and otherwise falls back to the items present
    ],
)
def test_calculate_limit(max_capacity: int, num_items: int, item_size: int, limit: int) -> None:
    assert calculate_limit(max_capacity, num_items, item_size) == limit


def test_walker_pads_every_field_to_a_chunk() -> None:
    walker = HashWalker()
    walker.put_uint64(1)
    walker.put_bool(True)
    walker.put_bytes(b"\xab")

    assert bytes(walker.buffer) == (
        b"\x01" + b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\xab" + b"\x00" * 31
    )


def test_walker_uint64_is_little_endian() -> None:
    walker = HashWalker()
    walker.put_uint64(4294967296)

    assert bytes(walker.buffer)[:8] == (4294967296).to_bytes(8, "little")


def test_walker_uint64_is_bounded() -> None:
    # Charon never hits this: its signed fields wrap through uint64(v) instead.
    # The spec rejects out-of-range values with the documented exception type.
    walker = HashWalker()
    walker.put_uint64(2**64 - 1)

    for value in (-1, 2**64):
        with pytest.raises(ValueError, match="out of range for a uint64"):
            walker.put_uint64(value)

        with pytest.raises(ValueError, match="out of range for a uint64"):
            walker.put_uint64_array([value], max_capacity=256)


def test_walker_put_bytes_merkleizes_over_32_bytes() -> None:
    walker = HashWalker()
    walker.put_bytes(b"\xcd" * 48)

    assert bytes(walker.buffer) == hashlib.sha256(b"\xcd" * 48 + b"\x00" * 16).digest()


def test_walker_merkleize_closes_a_container() -> None:
    walker = HashWalker()
    start = walker.index()
    walker.put_uint64(1)
    walker.put_uint64(2)
    walker.merkleize(start)

    expected = hashlib.sha256(
        (1).to_bytes(8, "little").ljust(32, b"\x00") + (2).to_bytes(8, "little").ljust(32, b"\x00")
    ).digest()

    assert walker.hash_root() == expected


def test_walker_mixin_distinguishes_list_lengths() -> None:
    # Two empty elements and three empty elements must not collide, which is what
    # the length mixin buys over a plain container.
    def root(count: int) -> bytes:
        walker = HashWalker()
        start = walker.index()
        for _ in range(count):
            walker.put_bytes(b"")

        walker.merkleize_with_mixin(start, count, 8)

        return walker.hash_root()

    assert root(2) != root(3)


def test_walker_hash_root_rejects_an_unbalanced_walk() -> None:
    walker = HashWalker()
    walker.put_uint64(1)
    walker.put_uint64(2)

    with pytest.raises(ValueError, match="incomplete walk"):
        walker.hash_root()


def test_put_byte_list_mixes_in_the_byte_length() -> None:
    walker = HashWalker()
    put_byte_list(walker, b"abc", 32, "field")
    mixin = (3).to_bytes(8, "little").ljust(32, b"\x00")

    assert walker.hash_root() == hashlib.sha256(b"abc".ljust(32, b"\x00") + mixin).digest()


def test_put_byte_list_rejects_an_over_long_value() -> None:
    with pytest.raises(ValueError, match="over the 4 byte limit"):
        put_byte_list(HashWalker(), b"toolong", 4, "field")


def test_put_bytes_n_left_pads() -> None:
    # Charon left-pads short fixed-size fields, so an absent signature hashes as
    # an all-zero one rather than as a right-padded stub.
    walker = HashWalker()
    put_bytes_n(walker, b"\x01", 4, "field")

    assert bytes(walker.buffer)[:4] == b"\x00\x00\x00\x01"


def test_put_bytes_n_rejects_an_over_long_value() -> None:
    with pytest.raises(ValueError, match="over the fixed length"):
        put_bytes_n(HashWalker(), b"\x01" * 5, 4, "field")


def test_walker_refuses_to_merkleize_an_unaligned_buffer() -> None:
    # Charon's SSZ library silently drops a trailing partial chunk here. No
    # cluster field leaves the buffer unaligned, so the spec fails loudly instead
    # of reproducing a truncation a future field could depend on by accident.
    walker = HashWalker()
    start = walker.index()
    walker.buffer += b"\x01" * 40

    with pytest.raises(ValueError, match="not chunk aligned"):
        walker.merkleize(start)
