"""Check the spec against the checked-in test vectors.

The vectors in `test_vectors/` are the artifact this repository publishes for
implementations to test against, so they are held to a stricter standard than an
ordinary fixture: the QBFT hashing vectors were produced by Charon itself, which
makes these tests a genuine cross-implementation check rather than a golden-file
snapshot of the spec's own output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dv_spec.crypto import bls, secp256k1
from dv_spec.encoding.proto import (
    encode_any_string,
    encode_duty,
    encode_unsigned_data_set,
)
from dv_spec.encoding.ssz import hash_proto
from dv_spec.subspecs.consensus.qbft.hashing import encode_qbft_msg, qbft_signing_root
from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTMsg
from dv_spec.subspecs.consensus.timer.timer import (
    eager_double_linear_deadline_nanos,
    get_duty_start_delay_nanos,
)
from dv_spec.subspecs.priority.message import PriorityMsg, PriorityTopicProposal
from dv_spec.subspecs.priority.scoring import calculate_result
from dv_spec.types.duty import Duty, DutyType

VECTOR_ROOT = Path(__file__).resolve().parent.parent / "test_vectors"


def load(suite: str) -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads((VECTOR_ROOT / f"{suite}.json").read_text())
    return data


def cases(suite: str, group: str) -> List[Any]:
    loaded = load(suite)[group]
    return [pytest.param(case, id=case["name"]) for case in loaded]


QBFT = "qbft_hashing"


@pytest.mark.parametrize("case", cases(QBFT, "duty"))
def test_duty_encoding_and_hash(case: Dict[str, Any]) -> None:
    duty = Duty(slot=case["input"]["slot"], type=DutyType(case["input"]["type"]))
    encoding = encode_duty(duty)

    assert encoding.hex() == case["encoding_hex"]
    assert hash_proto(encoding).hex() == case["hash_hex"]


@pytest.mark.parametrize("case", cases(QBFT, "unsigned_data_set"))
def test_unsigned_data_set_encoding_and_hash(case: Dict[str, Any]) -> None:
    entries = {key: bytes.fromhex(value) for key, value in case["input"]["set"].items()}
    encoding = encode_unsigned_data_set(entries)

    assert encoding.hex() == case["encoding_hex"]
    assert hash_proto(encoding).hex() == case["hash_hex"]


def qbft_msg(inputs: Dict[str, Any]) -> QBFTMsg:
    signature = inputs["signature"]
    return QBFTMsg(
        type=MsgType(inputs["type"]),
        duty=Duty(slot=inputs["slot"], type=DutyType(inputs["duty_type"])),
        peer_idx=inputs["peer_idx"],
        round=inputs["round"],
        prepared_round=inputs["prepared_round"],
        signature=bytes.fromhex(signature) if signature else None,
        value_hash=bytes.fromhex(inputs["value_hash"]),
        prepared_value_hash=bytes.fromhex(inputs["prepared_value_hash"]),
    )


@pytest.mark.parametrize("case", cases(QBFT, "qbft_signing_root"))
def test_qbft_signing_root(case: Dict[str, Any]) -> None:
    msg = qbft_msg(case["input"])

    assert encode_qbft_msg(msg, include_signature=False).hex() == case["encoding_hex"]
    assert qbft_signing_root(msg).hex() == case["hash_hex"]


@pytest.mark.parametrize("case", cases(QBFT, "any_string"))
def test_any_string_encoding_and_hash(case: Dict[str, Any]) -> None:
    encoding = encode_any_string(case["input"]["string_value"])

    assert encoding.hex() == case["encoding_hex"]
    assert hash_proto(encoding).hex() == case["hash_hex"]


@pytest.mark.parametrize("case", cases("timer_deadlines", "cases"))
def test_timer_deadline(case: Dict[str, Any]) -> None:
    inputs = case["input"]
    duty = Duty(slot=inputs["slot"], type=DutyType(inputs["duty_type"]))

    assert (
        get_duty_start_delay_nanos(duty.type, inputs["slot_duration_nanos"])
        == case["duty_start_delay_nanos"]
    )
    assert (
        eager_double_linear_deadline_nanos(
            duty,
            inputs["round"],
            inputs["genesis_time_nanos"],
            inputs["slot_duration_nanos"],
        )
        == case["deadline_nanos"]
    )


@pytest.mark.parametrize("case", cases("priority_scoring", "cases"))
def test_priority_scoring(case: Dict[str, Any]) -> None:
    inputs = case["input"]
    msgs = [
        PriorityMsg(
            duty=Duty(slot=inputs["slot"], type=DutyType.UNKNOWN),
            peer_id=peer["peer_id"],
            topics=[
                PriorityTopicProposal(topic=inputs["topic"], priorities=peer["priorities"]),
                PriorityTopicProposal(topic="ignored", priorities=[]),
            ],
        )
        for peer in inputs["peers"]
    ]

    result = calculate_result(msgs, inputs["min_required"])
    topic_result = next(topic for topic in result.topics if topic.topic == inputs["topic"])

    assert [
        {"priority": scored.priority, "score": scored.score} for scored in topic_result.priorities
    ] == case["result"]


def test_priority_scoring_is_independent_of_message_order() -> None:
    # The tie-broken cases are the ones that would expose an unstable sort, so
    # reverse the input and require an identical result.
    suite = load("priority_scoring")
    tied = [case for case in suite["cases"] if case["name"].startswith("deterministic ordering")]
    assert tied, "expected the tie-breaking cases to be present"

    for case in tied:
        inputs = case["input"]
        msgs = [
            PriorityMsg(
                duty=Duty(slot=inputs["slot"], type=DutyType.UNKNOWN),
                peer_id=peer["peer_id"],
                topics=[
                    PriorityTopicProposal(topic=inputs["topic"], priorities=peer["priorities"])
                ],
            )
            for peer in reversed(inputs["peers"])
        ]

        result = calculate_result(msgs, inputs["min_required"])
        assert [scored.priority for scored in result.topics[0].priorities] == [
            entry["priority"] for entry in case["result"]
        ]


BLS = "bls_threshold"


def bls_message() -> bytes:
    return bytes.fromhex(load(BLS)["message_hex"])


def bls_shares() -> Dict[int, Dict[str, Any]]:
    return {case["input"]["share_idx"]: case for case in load(BLS)["partials"]}


@pytest.mark.parametrize("case", cases(BLS, "keys"))
def test_bls_secret_to_pubkey(case: Dict[str, Any]) -> None:
    secret = bytes.fromhex(case["input"]["secret_hex"])

    assert bls.secret_to_pubkey(secret).hex() == case["pubkey_hex"]


@pytest.mark.parametrize("case", cases(BLS, "partials"))
def test_bls_partial_signature(case: Dict[str, Any]) -> None:
    secret = bytes.fromhex(case["input"]["secret_hex"])
    pubshare = bytes.fromhex(case["pubshare_hex"])

    assert bls.secret_to_pubkey(secret).hex() == case["pubshare_hex"]
    assert bls.sign(secret, bls_message()).hex() == case["signature_hex"]
    assert bls.verify(pubshare, bls_message(), bytes.fromhex(case["signature_hex"]))


def test_bls_group_signature() -> None:
    suite = load(BLS)
    secret = bytes.fromhex(suite["group_secret_hex"])
    pubkey = bytes.fromhex(suite["group_pubkey_hex"])

    assert bls.secret_to_pubkey(secret).hex() == suite["group_pubkey_hex"]
    assert bls.sign(secret, bls_message()).hex() == suite["group_signature_hex"]
    assert bls.verify(pubkey, bls_message(), bytes.fromhex(suite["group_signature_hex"]))


@pytest.mark.parametrize("case", cases(BLS, "threshold_aggregates"))
def test_bls_threshold_aggregate(case: Dict[str, Any]) -> None:
    shares = bls_shares()
    partials = {
        index: bytes.fromhex(shares[index]["signature_hex"])
        for index in case["input"]["share_indices"]
    }

    aggregate = bls.threshold_aggregate(partials)

    assert aggregate.hex() == case["signature_hex"]
    # The point of the suite: every quorum reconstructs the validator's own
    # signature, which verifies under the validator's own public key.
    assert aggregate.hex() == load(BLS)["group_signature_hex"]
    assert bls.verify(bytes.fromhex(load(BLS)["group_pubkey_hex"]), bls_message(), aggregate)


@pytest.mark.parametrize("case", cases(BLS, "recovery"))
def test_bls_recover_pubkey(case: Dict[str, Any]) -> None:
    shares = bls_shares()
    pubshares = {
        index: bytes.fromhex(shares[index]["pubshare_hex"])
        for index in case["input"]["share_indices"]
    }

    assert bls.recover_pubkey(pubshares).hex() == case["pubkey_hex"]


@pytest.mark.parametrize("case", cases(BLS, "plain_aggregate"))
def test_bls_plain_aggregate(case: Dict[str, Any]) -> None:
    suite = load(BLS)
    shares = bls_shares()
    indices = case["input"]["share_indices"]
    signatures = [bytes.fromhex(shares[index]["signature_hex"]) for index in indices]
    pubshares = [bytes.fromhex(shares[index]["pubshare_hex"]) for index in indices]

    aggregate = bls.aggregate(signatures)

    assert aggregate.hex() == case["signature_hex"]
    assert bls.verify_aggregate(pubshares, bls_message(), aggregate)
    # It is not the group signature, and does not verify under the group key.
    assert aggregate.hex() != suite["group_signature_hex"]
    assert not bls.verify(bytes.fromhex(suite["group_pubkey_hex"]), bls_message(), aggregate)


K1 = "secp256k1_signatures"


@pytest.mark.parametrize("case", cases(K1, "cases"))
def test_secp256k1_sign_and_recover(case: Dict[str, Any]) -> None:
    suite = load(K1)
    secret = bytes.fromhex(suite["secret_hex"])
    digest = bytes.fromhex(case["input"]["hash_hex"])

    signature = secp256k1.sign(secret, digest)

    assert signature.hex() == case["signature_hex"]
    assert secp256k1.recover(digest, signature).hex() == case["recovered_pubkey_hex"]
    assert secp256k1.secret_to_pubkey(secret).hex() == suite["pubkey_hex"]
    assert secp256k1.verify(bytes.fromhex(suite["pubkey_hex"]), digest, signature)


def test_secp256k1_signs_the_qbft_signing_root() -> None:
    # Chains the two suites: the hash signed here is the root the hashing suite
    # derives from a QBFT message.
    roots = {case["name"]: case["hash_hex"] for case in load(QBFT)["qbft_signing_root"]}
    signed = {case["name"]: case["input"]["hash_hex"] for case in load(K1)["cases"]}

    assert signed["qbft_attester_pre_prepare"] == roots["attester_pre_prepare"]


def test_signed_message_signing_root_ignores_signature() -> None:
    # Stated by the spec and asserted by the vectors; kept as a standalone test
    # because it is the property a receiver depends on to verify a signature.
    signed = load(QBFT)["qbft_signing_root"]
    roots = {case["name"]: case["hash_hex"] for case in signed}

    assert roots["attester_pre_prepare"] == roots["attester_pre_prepare_signed"]


def test_every_suite_declares_provenance() -> None:
    suites = sorted(VECTOR_ROOT.glob("*.json"))
    assert suites, "no vector suites found"

    for path in suites:
        suite = json.loads(path.read_text())
        provenance = suite.get("provenance", {})
        assert suite.get("suite") == path.stem, f"{path.name}: suite name must match filename"
        assert provenance.get("source") in {"charon", "spec"}, f"{path.name}: unknown source"
        assert provenance.get("charon_ref"), f"{path.name}: missing charon_ref"
