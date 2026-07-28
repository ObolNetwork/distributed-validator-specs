import pytest

from dv_spec.crypto import secp256k1

SECRET = bytes.fromhex("4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d")
DIGEST = bytes.fromhex("3a08c29e25a343e6e5a15c629a9b8ffa4f2b39294544f4ccea75dfe659e77f60")


def test_sign_recover_roundtrip() -> None:
    signature = secp256k1.sign(SECRET, DIGEST)

    assert len(signature) == secp256k1.SIGNATURE_LENGTH
    assert secp256k1.recover(DIGEST, signature) == secp256k1.secret_to_pubkey(SECRET)
    assert secp256k1.verify(secp256k1.secret_to_pubkey(SECRET), DIGEST, signature)


def test_signing_is_deterministic() -> None:
    # RFC 6979 nonce: the same key and digest always give the same bytes, which
    # is what makes these vectors reproducible.
    assert secp256k1.sign(SECRET, DIGEST) == secp256k1.sign(SECRET, DIGEST)


def test_verify_rejects_another_key() -> None:
    other = secp256k1.secret_to_pubkey(bytes.fromhex("11" * 32))

    assert not secp256k1.verify(other, DIGEST, secp256k1.sign(SECRET, DIGEST))


def test_recovery_id_offset_is_accepted() -> None:
    signature = secp256k1.sign(SECRET, DIGEST)
    offset = signature[:-1] + bytes([signature[-1] + secp256k1.RECOVERY_ID_OFFSET])

    assert secp256k1.normalise_recovery_id(offset) == signature
    assert secp256k1.recover(DIGEST, offset) == secp256k1.recover(DIGEST, signature)


def test_normalise_recovery_id_rejects_malformed_input() -> None:
    with pytest.raises(ValueError, match="must be 65 bytes"):
        secp256k1.normalise_recovery_id(b"\x01" * 64)

    with pytest.raises(ValueError, match="invalid recovery id"):
        secp256k1.normalise_recovery_id(b"\x01" * 64 + bytes([7]))


# R above the curve order, and R = S = 0: well-formed lengths, garbage contents.
GARBAGE_SIGNATURES = [b"\xff" * 64 + b"\x00", b"\x00" * 65]


@pytest.mark.parametrize("signature", GARBAGE_SIGNATURES)
def test_recover_raises_value_error_on_garbage_signature(signature: bytes) -> None:
    # The backend's own exception types must not escape: receiver-side
    # validation handles ValueError and nothing else.
    with pytest.raises(ValueError, match="invalid signature"):
        secp256k1.recover(DIGEST, signature)


@pytest.mark.parametrize("signature", GARBAGE_SIGNATURES)
def test_verify_returns_false_on_garbage_signature(signature: bytes) -> None:
    assert not secp256k1.verify(secp256k1.secret_to_pubkey(SECRET), DIGEST, signature)


def test_verify_still_raises_on_wrong_length_digest() -> None:
    # A bad digest is a caller bug, not attacker-controlled input.
    with pytest.raises(ValueError, match="hash must be 32 bytes"):
        secp256k1.verify(secp256k1.secret_to_pubkey(SECRET), b"\x01" * 31, b"\x00" * 65)


@pytest.mark.parametrize("length", [0, 31, 33])
def test_secret_length_is_enforced(length: int) -> None:
    with pytest.raises(ValueError, match="secret must be 32 bytes"):
        secp256k1.sign(b"\x01" * length, DIGEST)

    with pytest.raises(ValueError, match="secret must be 32 bytes"):
        secp256k1.secret_to_pubkey(b"\x01" * length)


@pytest.mark.parametrize("length", [0, 31, 33])
def test_hash_length_is_enforced(length: int) -> None:
    with pytest.raises(ValueError, match="hash must be 32 bytes"):
        secp256k1.sign(SECRET, b"\x01" * length)

    with pytest.raises(ValueError, match="hash must be 32 bytes"):
        secp256k1.recover(b"\x01" * length, secp256k1.sign(SECRET, DIGEST))
