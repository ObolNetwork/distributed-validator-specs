import pytest

from dv_spec.crypto import bls

SECRET = bytes.fromhex("598d4150de5b558716e1ca4df2853d696c1cc47f3af380d9ac3db876ebd038c5")
MESSAGE = b"a message"


def test_bls_modulus_is_the_curve_order() -> None:
    assert bls.BLS_MODULUS == (
        52435875175126190479447740508185965837690552500527637822603658699938581184513
    )


@pytest.mark.parametrize("length", [0, 31, 33])
def test_secret_must_be_32_bytes(length: int) -> None:
    with pytest.raises(ValueError, match="must be 32 bytes"):
        bls.secret_to_int(b"\x01" * length)


@pytest.mark.parametrize(
    "secret",
    [b"\x00" * 32, bls.BLS_MODULUS.to_bytes(32, "big")],
)
def test_secret_must_be_in_range(secret: bytes) -> None:
    with pytest.raises(ValueError, match="out of range"):
        bls.secret_to_int(secret)


def test_sign_verify_roundtrip() -> None:
    pubkey = bls.secret_to_pubkey(SECRET)
    signature = bls.sign(SECRET, MESSAGE)

    assert len(pubkey) == bls.PUBKEY_LENGTH
    assert len(signature) == bls.SIGNATURE_LENGTH
    assert bls.verify(pubkey, MESSAGE, signature)
    assert not bls.verify(pubkey, b"another message", signature)


def test_aggregate_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="no signatures"):
        bls.aggregate([])


def test_interpolation_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="no points"):
        bls.threshold_aggregate({})

    with pytest.raises(ValueError, match="no points"):
        bls.recover_pubkey({})


@pytest.mark.parametrize(
    ("index", "indices"),
    [(4, [1, 2, 3]), (1, [1, 1, 2]), (0, [0, 1, 2])],
)
def test_lagrange_coefficient_rejects_bad_indices(index: int, indices: list[int]) -> None:
    with pytest.raises(ValueError):
        bls.lagrange_coefficient(index, indices)


def test_lagrange_coefficients_interpolate_a_constant() -> None:
    # The coefficients of any index set sum to 1 mod r, which is what makes the
    # interpolation evaluate a constant polynomial to itself.
    for indices in ([1], [1, 2], [1, 2, 3], [2, 3, 5, 7]):
        total = sum(bls.lagrange_coefficient(i, indices) for i in indices) % bls.BLS_MODULUS
        assert total == 1
