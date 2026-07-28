import pytest

from dv_spec.subspecs.dkg.node_sigs import (
    NODE_SIG_MSG_ID,
    NONE_DATA,
    MsgNodeSig,
    collect_node_sigs,
    verify_node_sig_msg,
)

NUM_PEERS = 4
OWN_PEER_INDEX = 0


def test_msg_id_is_unversioned() -> None:
    assert NODE_SIG_MSG_ID == "/charon/dkg/node_sig"


def test_none_data_sentinel() -> None:
    assert NONE_DATA == bytes([0xDE, 0xAD, 0xBE, 0xEF])


def test_verify_node_sig_msg_accepts_matching_sender() -> None:
    msg = MsgNodeSig(signature=b"\x01" * 65, peer_index=2)
    verify_node_sig_msg(
        msg, sender_peer_index=2, own_peer_index=OWN_PEER_INDEX, num_peers=NUM_PEERS
    )


@pytest.mark.parametrize(
    ("peer_index", "sender_peer_index", "error"),
    [
        (NUM_PEERS, NUM_PEERS, "invalid peer index"),
        (OWN_PEER_INDEX, OWN_PEER_INDEX, "invalid peer index"),
        (2, 3, "sender peer ID does not match claimed peer index"),
    ],
)
def test_verify_node_sig_msg_rejects(peer_index: int, sender_peer_index: int, error: str) -> None:
    msg = MsgNodeSig(signature=b"\x01" * 65, peer_index=peer_index)
    with pytest.raises(ValueError, match=error):
        verify_node_sig_msg(
            msg,
            sender_peer_index=sender_peer_index,
            own_peer_index=OWN_PEER_INDEX,
            num_peers=NUM_PEERS,
        )


def test_collect_node_sigs_waits_for_every_peer() -> None:
    sigs = {index: bytes([index]) * 65 for index in range(NUM_PEERS - 1)}
    assert collect_node_sigs(sigs, NUM_PEERS) is None

    sigs[NUM_PEERS - 1] = bytes([NUM_PEERS - 1]) * 65
    collected = collect_node_sigs(sigs, NUM_PEERS)
    assert collected == [bytes([index]) * 65 for index in range(NUM_PEERS)]


def test_collect_node_sigs_drops_sentinels() -> None:
    sigs = {index: bytes([index]) * 65 for index in range(NUM_PEERS)}
    sigs[1] = NONE_DATA

    collected = collect_node_sigs(sigs, NUM_PEERS)

    assert collected == [bytes([0]) * 65, bytes([2]) * 65, bytes([3]) * 65]
