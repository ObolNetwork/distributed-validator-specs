import hashlib

import pytest

from dv_spec.encoding.ssz import (
    ZERO_CHUNK,
    ZERO_HASHES,
    chunk_count_depth,
    chunkify,
    hash_proto,
    merkleize,
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
