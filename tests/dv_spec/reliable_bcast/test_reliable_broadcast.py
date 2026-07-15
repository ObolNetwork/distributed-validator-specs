from hashlib import sha256

from dv_spec.subspecs.reliable_bcast import (
    AnyMessage,
    BCastMessage,
    BCastSigRequest,
    BCastSigResponse,
    compute_any_hash,
)


def test_compute_any_hash_concatenates_type_and_value() -> None:
    any_msg = AnyMessage(type_url="type.googleapis.com/foo.Bar", value=b"payload")
    expect = sha256(any_msg.type_url.encode("utf-8") + b"payload").digest()
    assert compute_any_hash(any_msg) == expect


def test_model_construction() -> None:
    any_msg = AnyMessage(type_url="/dv_spec/test", value=b"abc")

    req = BCastSigRequest(message_id="node_pubkeys", message=any_msg)
    assert req.message_id == "node_pubkeys"
    assert req.message.value == b"abc"

    resp = BCastSigResponse(signature=b"s" * 65)
    assert len(resp.signature) == 65

    bmsg = BCastMessage(message_id="node_pubkeys", message=any_msg, signatures=[b"s" * 65])
    assert bmsg.signatures and len(bmsg.signatures[0]) == 65
