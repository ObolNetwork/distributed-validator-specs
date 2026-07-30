import pytest

from dv_spec.subspecs.sigagg.threshold import (
    PartialSignature,
    select_threshold_matching,
    store_partial_signature,
)
from dv_spec.types.duty import DutyType

THRESHOLD = 3
ROOT_A = b"\xaa" * 32
ROOT_B = b"\xbb" * 32


def par_sig(share_idx: int, root: bytes = ROOT_A) -> PartialSignature:
    return PartialSignature(
        share_idx=share_idx,
        signature=bytes([share_idx]) * 96,
        message_root=root,
    )


def test_share_idx_is_one_based() -> None:
    with pytest.raises(ValueError):
        PartialSignature(share_idx=0, signature=b"\x01" * 96, message_root=ROOT_A)


@pytest.mark.parametrize("length", [0, 95, 97])
def test_signature_must_be_96_bytes(length: int) -> None:
    with pytest.raises(ValueError):
        PartialSignature(share_idx=1, signature=b"\x01" * length, message_root=ROOT_A)


def test_store_partial_signature_appends_new_share() -> None:
    stored = store_partial_signature([par_sig(1)], par_sig(2))
    assert stored is not None
    assert [sig.share_idx for sig in stored] == [1, 2]


def test_store_partial_signature_ignores_exact_duplicate() -> None:
    assert store_partial_signature([par_sig(1)], par_sig(1)) is None


def test_store_partial_signature_rejects_mismatching_data() -> None:
    conflicting = PartialSignature(share_idx=1, signature=b"\xff" * 96, message_root=ROOT_A)
    with pytest.raises(ValueError, match="mismatching partial signed data"):
        store_partial_signature([par_sig(1)], conflicting)


def test_select_threshold_matching_needs_threshold_signatures() -> None:
    sigs = [par_sig(1), par_sig(2)]
    assert select_threshold_matching(DutyType.ATTESTER, sigs, THRESHOLD) is None


def test_select_threshold_matching_groups_by_message_root() -> None:
    # Three signatures, but only two agree on the message root.
    sigs = [par_sig(1), par_sig(2), par_sig(3, ROOT_B)]
    assert select_threshold_matching(DutyType.ATTESTER, sigs, THRESHOLD) is None

    sigs.append(par_sig(4))
    selected = select_threshold_matching(DutyType.ATTESTER, sigs, THRESHOLD)
    assert selected is not None
    assert [sig.share_idx for sig in selected] == [1, 2, 4]


def test_select_threshold_matching_fires_exactly_once() -> None:
    sigs = [par_sig(1), par_sig(2), par_sig(3)]
    assert select_threshold_matching(DutyType.ATTESTER, sigs, THRESHOLD) is not None

    # A fourth matching signature must not re-trigger aggregation.
    sigs.append(par_sig(4))
    assert select_threshold_matching(DutyType.ATTESTER, sigs, THRESHOLD) is None


def test_select_threshold_matching_ignores_root_for_signature_duty() -> None:
    sigs = [par_sig(1), par_sig(2, ROOT_B), par_sig(3)]
    selected = select_threshold_matching(DutyType.SIGNATURE, sigs, THRESHOLD)
    assert selected is not None
    assert [sig.share_idx for sig in selected] == [1, 2, 3]

    sigs.append(par_sig(4))
    assert select_threshold_matching(DutyType.SIGNATURE, sigs, THRESHOLD) is None
