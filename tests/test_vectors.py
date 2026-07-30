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

from dv_spec.cluster.definition import Definition
from dv_spec.cluster.hashing import (
    config_hash,
    definition_hash,
    lock_hash,
    verify_definition_hashes,
    verify_lock_hash,
)
from dv_spec.cluster.lock import Lock
from dv_spec.cluster.verification import (
    verify_node_signatures,
    verify_pubshare_counts,
    verify_shares_reconstruct,
    verify_signature_aggregate,
)
from dv_spec.crypto import bls, secp256k1
from dv_spec.encoding.proto import (
    encode_any_string,
    encode_duty,
    encode_unsigned_data_set,
)
from dv_spec.encoding.ssz import hash_proto
from dv_spec.subspecs.consensus.cryptography import hash_value
from dv_spec.subspecs.consensus.qbft.definition import Definition as QBFTDefinition
from dv_spec.subspecs.consensus.qbft.hashing import encode_qbft_msg, qbft_signing_root
from dv_spec.subspecs.consensus.qbft.message import (
    MAX_CONSENSUS_MSG_SIZE,
    MsgType,
    QBFTConsensusMsg,
    QBFTMsg,
    verify_msg_limits,
)
from dv_spec.subspecs.consensus.qbft.protocol import QBFTConsensus
from dv_spec.subspecs.consensus.qbft.transport import PeerInfo, Transport
from dv_spec.subspecs.consensus.timer.timer import (
    eager_double_linear_deadline_nanos,
    get_duty_start_delay_nanos,
)
from dv_spec.subspecs.parsigex.helpers import validate_exchange_peers, verify_peer_share_idx
from dv_spec.subspecs.parsigex.message import ParSignedData
from dv_spec.subspecs.priority.message import PriorityMsg, PriorityTopicProposal
from dv_spec.subspecs.priority.scoring import calculate_result
from dv_spec.types.duty import Duty, DutyType

VECTOR_ROOT = Path(__file__).resolve().parent.parent / "test_vectors"


def load(suite: str) -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads((VECTOR_ROOT / f"{suite}.json").read_text())
    return data


def cases(suite: str, group: str) -> List[Any]:
    loaded = load(suite)[group]
    # An empty group would parametrize zero tests and pass silently, so a
    # vector file losing its cases must fail loudly instead.
    assert loaded, f"vector suite {suite!r} has no cases in group {group!r}"

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
                PriorityTopicProposal(topic=inputs["ignored_topic"], priorities=[]),
            ],
        )
        for peer in inputs["peers"]
    ]

    result = calculate_result(msgs, inputs["min_required"])
    topic_result = next(topic for topic in result.topics if topic.topic == inputs["topic"])

    assert [
        {"priority": scored.priority, "score": scored.score} for scored in topic_result.priorities
    ] == case["result"]

    # The empty topic every peer proposes must survive into the result with no
    # priorities — dropped-topic and nothing-met-the-threshold are different
    # outcomes, and the suite pins the distinction.
    ignored = next(topic for topic in result.topics if topic.topic == inputs["ignored_topic"])
    assert ignored.priorities == []


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


CLUSTER = "cluster_hashing"


@pytest.mark.parametrize("case", cases(CLUSTER, "definition"))
def test_cluster_definition_hashes(case: Dict[str, Any]) -> None:
    definition = Definition.model_validate(case["input"])

    assert config_hash(definition).hex() == case["config_hash"]
    assert definition_hash(definition).hex() == case["definition_hash"]
    # The hashes the file stores must agree with its content, which is what a
    # reader checks before trusting any signature over them.
    verify_definition_hashes(definition)


def test_cluster_config_hash_survives_signing() -> None:
    # The reason the config hash exists. Operators sign it while ENRs and other
    # operators' signatures are still arriving, so it must not move when they do.
    by_name = {case["name"]: case for case in load(CLUSTER)["definition"]}
    unsigned = Definition.model_validate(by_name["unsigned_single_operator"]["input"])
    signed = Definition.model_validate(by_name["signed_single_operator"]["input"])

    assert signed.operators[0].config_signature, "the signed case must carry signatures"
    assert not unsigned.operators[0].config_signature
    assert config_hash(signed) == config_hash(unsigned)
    assert definition_hash(signed) != definition_hash(unsigned)


@pytest.mark.parametrize("case", cases(CLUSTER, "lock"))
def test_cluster_lock_hash(case: Dict[str, Any]) -> None:
    lock = Lock.model_validate(case["input"])

    assert lock_hash(lock).hex() == case["lock_hash"]
    verify_lock_hash(lock)


@pytest.mark.parametrize("case", cases(CLUSTER, "definition"))
def test_cluster_definition_json_round_trips(case: Dict[str, Any]) -> None:
    definition = Definition.model_validate(case["input"])
    reparsed = Definition.model_validate(json.loads(definition.model_dump_json()))

    assert reparsed == definition


@pytest.mark.parametrize("case", cases(CLUSTER, "lock"))
def test_cluster_lock_json_round_trips(case: Dict[str, Any]) -> None:
    # The models have to read Charon's file format, not a transcription of it,
    # so a plain dump must re-parse to an identical lock — every field, not just
    # the ones the lock hash covers.
    lock = Lock.model_validate(case["input"])
    reparsed = Lock.model_validate(json.loads(lock.model_dump_json()))

    assert reparsed == lock
    assert lock_hash(reparsed) == lock_hash(lock)


def test_cluster_lock_signatures_verify() -> None:
    case = next(entry for entry in load(CLUSTER)["lock"] if entry["name"] == "real_keys_3_of_4")
    lock = Lock.model_validate(case["input"])
    node_pubkeys = [bytes.fromhex(pubkey) for pubkey in case["node_pubkeys"]]

    verify_pubshare_counts(lock)
    verify_shares_reconstruct(lock)

    assert verify_signature_aggregate(lock)
    assert verify_node_signatures(lock, node_pubkeys)


def test_cluster_lock_aggregate_covers_the_lock_hash() -> None:
    # A lock whose content is edited after signing must fail, otherwise the
    # aggregate would attest to a cluster nobody agreed to.
    case = next(entry for entry in load(CLUSTER)["lock"] if entry["name"] == "real_keys_3_of_4")
    lock = Lock.model_validate(case["input"])
    tampered = lock.model_copy(
        update={"definition": lock.definition.model_copy(update={"threshold": 2})}
    )

    assert lock_hash(tampered) != lock_hash(lock)
    assert not verify_signature_aggregate(tampered)


def test_cluster_lock_reuses_the_bls_threshold_sharing() -> None:
    # Chains the two suites: the lock's public shares are the same sharing
    # bls_threshold.json pins, so its group key must reconstruct from them.
    case = next(entry for entry in load(CLUSTER)["lock"] if entry["name"] == "real_keys_3_of_4")
    lock = Lock.model_validate(case["input"])
    pubshares = {
        partial["input"]["share_idx"]: partial["pubshare_hex"] for partial in load(BLS)["partials"]
    }

    assert [share.hex() for share in lock.validators[0].pubshares] == [
        pubshares[index] for index in sorted(pubshares)
    ]
    assert lock.validators[0].pubkey.hex() == load(BLS)["group_pubkey_hex"]


# --- rejection suites -------------------------------------------------------
#
# These consume the vectors the way an implementation would: every input is built
# from the case's `input` object, not from the helper that generated it. Sharing a
# builder with `scripts/generate_test_vectors.py` would let a wrong count agree
# with itself. One overlap remains: the decided-resends replay forges its decided
# state by planting a commit quorum, the same technique the generator uses, so a
# change to how the spec detects decision moves both together. The Go consumer
# suite drives a real instance to decision instead.

LIMITS = "qbft_msg_limits"
RESENDS = "qbft_decided_resends"
BINDING = "parsigex_sender_binding"


@pytest.mark.parametrize("case", cases(LIMITS, "counts"))
def test_qbft_msg_limit_counts(case: Dict[str, Any]) -> None:
    inputs = case["input"]

    # The limits the case ships as guidance must be charon's formulas, or an
    # implementer trusting the metadata is misled even when the verdict is right.
    assert case["max_justifications"] == 2 * inputs["nodes"]
    assert case["max_values"] == 2 * (inputs["justification_count"] + 1)

    duty = Duty(slot=1, type=DutyType.ATTESTER)
    template = QBFTMsg(type=MsgType.PREPARE, duty=duty, peer_idx=0, round=1)
    consensus_msg = QBFTConsensusMsg(
        msg=template,
        justification=[template] * inputs["justification_count"],
        values=[bytes([index % 256]) for index in range(inputs["value_count"])],
    )

    if case["accepted"]:
        verify_msg_limits(consensus_msg, inputs["nodes"])
        return

    with pytest.raises(ValueError) as raised:
        verify_msg_limits(consensus_msg, inputs["nodes"])

    # The reason matters as much as the rejection: an implementation that rejected
    # on the value count where charon rejects on the justification count would
    # disagree the moment both limits are exceeded.
    expected = "justifications" if case["reason"] == "too_many_justifications" else "values"
    assert expected in str(raised.value)


@pytest.mark.parametrize("case", cases(LIMITS, "wire_size"))
def test_qbft_msg_wire_size_limit(case: Dict[str, Any]) -> None:
    assert (case["input"]["wire_size_bytes"] <= MAX_CONSENSUS_MSG_SIZE) == case["accepted"]
    assert case["reason"] == (None if case["accepted"] else "msg_too_large")


@pytest.mark.parametrize("case", cases(RESENDS, "cases"))
def test_qbft_decided_resends(case: Dict[str, Any]) -> None:
    inputs = case["input"]
    nodes = inputs["nodes"]
    duty = Duty(slot=100, type=DutyType.ATTESTER)
    proposal_value = b"test_block"

    consensus = QBFTConsensus(
        d=QBFTDefinition(nodes=nodes),
        t=Transport(
            private_key=b"test_key" * 4,
            peers=[
                PeerInfo(peer_idx=index, public_key=b"test_key", peer_id=f"peer_{index}")
                for index in range(nodes)
            ],
        ),
        duty=duty,
        peer=0,
        proposal_value=proposal_value,
    )
    consensus.q_commit = [
        QBFTMsg(
            type=MsgType.COMMIT,
            duty=duty,
            peer_idx=index,
            round=inputs["decided_round"],
            signature=b"0" * 65,
            value_hash=hash_value(proposal_value),
        )
        for index in range(nodes - 1)
    ]

    rebroadcast = []
    for event in inputs["events"]:
        responses = consensus.handle_message(
            QBFTConsensusMsg(
                msg=QBFTMsg(
                    type=MsgType.ROUND_CHANGE,
                    duty=duty,
                    peer_idx=event["source"],
                    round=event["round"],
                    signature=b"0" * 65,
                )
            )
        )
        # What comes back must be the decision itself — the decided value under
        # a DECIDED type, justified by the commit quorum — not merely something.
        for response in responses:
            assert response.msg.type == MsgType.DECIDED
            assert response.msg.value_hash == hash_value(proposal_value)
            assert response.justification == consensus.q_commit

        rebroadcast.append(bool(responses))

    assert rebroadcast == case["rebroadcast"]
    assert sum(rebroadcast) == case["total_rebroadcasts"]


@pytest.mark.parametrize("case", cases(BINDING, "cases"))
def test_parsigex_sender_binding(case: Dict[str, Any]) -> None:
    inputs = case["input"]
    # model_construct bypasses validation, so the non-positive share index reaches
    # the verifier. Charon's type carries no such constraint, and folds the
    # non-positive and mismatched cases into one rejection.
    data = ParSignedData.model_construct(
        data=b"", signature=b"\x00" * 65, share_idx=inputs["share_idx"]
    )

    if case["accepted"]:
        verify_peer_share_idx(inputs["share_idx_by_peer"], inputs["sender"], data)
        return

    with pytest.raises(ValueError) as raised:
        verify_peer_share_idx(inputs["share_idx_by_peer"], inputs["sender"], data)

    expected = "unknown peer" if case["reason"] == "unknown_peer" else "does not match"
    assert expected in str(raised.value)


@pytest.mark.parametrize("case", cases(BINDING, "peer_map"))
def test_parsigex_peer_map_validation(case: Dict[str, Any]) -> None:
    inputs = case["input"]

    if case["accepted"]:
        validate_exchange_peers(inputs["peers"], inputs["share_idx_by_peer"], inputs["peer_idx"])
        return

    with pytest.raises(ValueError, match="missing valid share index"):
        validate_exchange_peers(inputs["peers"], inputs["share_idx_by_peer"], inputs["peer_idx"])


def test_rejection_suites_carry_both_verdicts() -> None:
    # A suite that drifted to all-accept or all-reject would still pass every case
    # above while testing nothing, so pin that each carries both.
    for suite, groups in (
        (LIMITS, ("counts", "wire_size")),
        (BINDING, ("cases", "peer_map")),
    ):
        loaded = load(suite)
        for group in groups:
            verdicts = {case["accepted"] for case in loaded[group]}
            assert verdicts == {True, False}, f"{suite}/{group} must cover both verdicts"

    for case in load(RESENDS)["cases"]:
        assert set(case["rebroadcast"]) == {True, False}, f"{case['name']} must cover both"


def test_every_suite_declares_provenance() -> None:
    suites = sorted(VECTOR_ROOT.glob("*.json"))
    assert suites, "no vector suites found"

    for path in suites:
        suite = json.loads(path.read_text())
        provenance = suite.get("provenance", {})
        assert suite.get("suite") == path.stem, f"{path.name}: suite name must match filename"
        assert provenance.get("source") in {"charon", "spec"}, f"{path.name}: unknown source"
        assert provenance.get("charon_ref"), f"{path.name}: missing charon_ref"
