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
    session_nonce,
)


def test_session_nonce_derivation():
    sid = b"\x11" * 32
    assert session_nonce(sid) == sha256(sid).digest()


def test_message_models_construct():
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
