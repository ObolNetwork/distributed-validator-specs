import pytest

from dv_spec.subspecs.sigagg.aggregation import (
    BLS_MODULUS,
    aggregation_coefficients,
    lagrange_coefficient,
    select_aggregation_inputs,
    verify_share_idx,
)
from dv_spec.subspecs.sigagg.threshold import PartialSignature

THRESHOLD = 3
ROOT = b"\xaa" * 32


def par_sig(share_idx: int) -> PartialSignature:
    return PartialSignature(
        share_idx=share_idx,
        signature=bytes([share_idx]) * 96,
        message_root=ROOT,
    )


def test_verify_share_idx_resolves_public_share() -> None:
    public_shares = {1: b"\x01" * 48, 2: b"\x02" * 48}
    assert verify_share_idx(2, public_shares) == b"\x02" * 48


def test_verify_share_idx_rejects_unknown_share() -> None:
    with pytest.raises(ValueError, match="invalid shareIdx 3"):
        verify_share_idx(3, {1: b"\x01" * 48})


@pytest.mark.parametrize(
    ("index", "indices", "expected"),
    [
        (1, [1, 2, 3], 3),
        (2, [1, 2, 3], BLS_MODULUS - 3),
        (3, [1, 2, 3], 1),
        (1, [1], 1),
        (2, [2, 4], 2),
        (4, [2, 4], BLS_MODULUS - 1),
    ],
)
def test_lagrange_coefficient(index: int, indices: list[int], expected: int) -> None:
    assert lagrange_coefficient(index, indices) == expected


def test_lagrange_coefficients_sum_to_one() -> None:
    # Interpolating the constant polynomial f(x) = 1 at zero must yield 1.
    for indices in ([1, 2, 3], [1, 3, 4], [2, 3, 5, 7]):
        total = sum(aggregation_coefficients(indices).values()) % BLS_MODULUS
        assert total == 1


def test_lagrange_coefficient_rejects_invalid_index_sets() -> None:
    with pytest.raises(ValueError, match="not among the aggregation indices"):
        lagrange_coefficient(4, [1, 2, 3])

    with pytest.raises(ValueError, match="duplicate share index"):
        lagrange_coefficient(1, [1, 2, 2])

    with pytest.raises(ValueError, match="1-based"):
        lagrange_coefficient(1, [0, 1])


def test_select_aggregation_inputs_keys_by_share_index() -> None:
    inputs = select_aggregation_inputs([par_sig(1), par_sig(2), par_sig(3)], THRESHOLD)
    assert sorted(inputs) == [1, 2, 3]
    assert inputs[2] == bytes([2]) * 96


def test_select_aggregation_inputs_requires_threshold_signatures() -> None:
    with pytest.raises(ValueError, match="require threshold signatures"):
        select_aggregation_inputs([par_sig(1), par_sig(2)], THRESHOLD)


def test_select_aggregation_inputs_requires_distinct_share_indices() -> None:
    duplicated = [
        par_sig(1),
        par_sig(2),
        PartialSignature(share_idx=2, signature=b"\xff" * 96, message_root=ROOT),
    ]
    with pytest.raises(ValueError, match="less than threshold"):
        select_aggregation_inputs(duplicated, THRESHOLD)
