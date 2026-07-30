from dv_spec.subspecs.consensus.qbft.hashing import encode_qbft_msg, qbft_signing_root
from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTMsg
from dv_spec.types.duty import Duty, DutyType

SIGNATURE = b"\xdd" * 65


def signed_msg() -> QBFTMsg:
    return QBFTMsg(
        type=MsgType.PREPARE,
        duty=Duty(slot=42, type=DutyType.ATTESTER),
        peer_idx=1,
        round=2,
        signature=SIGNATURE,
        value_hash=b"\xaa" * 32,
    )


def test_signature_appears_only_when_requested() -> None:
    msg = signed_msg()

    with_sig = encode_qbft_msg(msg, include_signature=True)
    without_sig = encode_qbft_msg(msg, include_signature=False)

    assert SIGNATURE in with_sig
    assert SIGNATURE not in without_sig
    assert len(with_sig) == len(without_sig) + len(SIGNATURE) + 2  # tag + length prefix


def test_signing_root_excludes_the_signature() -> None:
    signed = signed_msg()
    unsigned = signed.model_copy(update={"signature": None})

    assert qbft_signing_root(signed) == qbft_signing_root(unsigned)


def test_absent_value_hash_encodes_as_the_zero_hash() -> None:
    absent = QBFTMsg(
        type=MsgType.PREPARE, duty=Duty(slot=1, type=DutyType.ATTESTER), peer_idx=0, round=1
    )
    zeroed = absent.model_copy(update={"value_hash": b"\x00" * 32})

    assert qbft_signing_root(absent) == qbft_signing_root(zeroed)
