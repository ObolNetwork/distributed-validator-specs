from hashlib import sha256

from dv_spec.subspecs.dkg.pedersen import (
    NodePubKeyMessage,
    NodePubKeyShares,
    PedersenDeal,
    PedersenDealBundle,
    PedersenJustification,
    PedersenJustificationBundle,
    PedersenResponse,
    PedersenResponseBundle,
    ValidatorPubKeyShareMessage,
    generate_nonce_from_node_pubkeys,
)


def test_generate_nonce_from_node_pubkeys() -> None:
    # Three deterministic pubkeys (already marshaled bytes)
    pks = [b"pk1", b"pk2", b"pk3"]
    expect = sha256(b"".join(pks)).digest()
    assert generate_nonce_from_node_pubkeys(pks) == expect


def test_message_models_construct() -> None:
    sid = b"\x01" * 32
    npk = NodePubKeyMessage(session_id=sid, public_key=b"pk")
    assert npk.session_id == sid
    assert npk.public_key == b"pk"

    shares = NodePubKeyShares(public_key_shares=[b"ps1", b"ps2"])
    npk2 = NodePubKeyMessage(session_id=sid, public_key=b"pk2", shares=shares)
    assert npk2.shares is not None and len(npk2.shares.public_key_shares) == 2

    deal = PedersenDeal(share_index=0, encrypted_share=b"ct")
    db = PedersenDealBundle(
        dealer_index=0,
        deals=[deal],
        public=[b"p0"],
        session_id=sid,
        signature=b"sig",
    )
    assert db.deals[0].encrypted_share == b"ct"

    resp = PedersenResponse(dealer_index=0, status=True)
    rb = PedersenResponseBundle(
        share_index=0,
        responses=[resp],
        session_id=sid,
        signature=b"rsig",
    )
    assert rb.responses[0].status is True

    just = PedersenJustification(share_index=0, share=b"sc")
    jb = PedersenJustificationBundle(
        dealer_index=0,
        justifications=[just],
        session_id=sid,
        signature=b"jsig",
    )
    assert jb.justifications[0].share_index == 0

    vps = ValidatorPubKeyShareMessage(session_id=sid, public_key_share=b"vps")
    assert vps.public_key_share == b"vps"
