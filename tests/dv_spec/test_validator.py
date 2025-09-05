"""Tests for distributed validator specifications."""

import pytest

from dv_spec import DistributedValidator, ValidatorCluster, hello_distributed_validator
from dv_spec.types import Bytes32, Uint64


def test_hello_distributed_validator() -> None:
    """Test the hello world function."""
    result = hello_distributed_validator()
    assert result == "Hello from the Obol Distributed Validator Network!"


def test_distributed_validator_creation() -> None:
    """Test creating a basic distributed validator."""
    validator = DistributedValidator(
        validator_index=Uint64(1),
        pubkey=Bytes32(b"a" * 32),
        cluster_id=Bytes32(b"cluster123" + b"\x00" * 22),
        operators=[Bytes32(b"operator1" + b"\x00" * 23), Bytes32(b"operator2" + b"\x00" * 23)],
        threshold=Uint64(2),
    )

    assert validator.validator_index == 1
    assert validator.active is True
    assert validator.version == "1.0.0"
    assert len(validator.operators) == 2
    assert validator.threshold == 2


def test_distributed_validator_validation() -> None:
    """Test that validation works correctly."""
    # Test empty operators list fails
    with pytest.raises(ValueError):
        DistributedValidator(
            validator_index=Uint64(1),
            pubkey=Bytes32(b"a" * 32),
            cluster_id=Bytes32(b"cluster123" + b"\x00" * 22),
            operators=[],  # Empty list should fail
            threshold=Uint64(2),
        )


def test_validator_cluster_creation() -> None:
    """Test creating a validator cluster."""
    validator1 = DistributedValidator(
        validator_index=Uint64(1),
        pubkey=Bytes32(b"a" * 32),
        cluster_id=Bytes32(b"cluster123" + b"\x00" * 22),
        operators=[Bytes32(b"operator1" + b"\x00" * 23)],
        threshold=Uint64(1),
    )

    validator2 = DistributedValidator(
        validator_index=Uint64(2),
        pubkey=Bytes32(b"b" * 32),
        cluster_id=Bytes32(b"cluster123" + b"\x00" * 22),
        operators=[Bytes32(b"operator1" + b"\x00" * 23)],
        threshold=Uint64(1),
    )

    cluster = ValidatorCluster(
        cluster_id=Bytes32(b"cluster123" + b"\x00" * 22),
        validators=[validator1, validator2],
        cluster_name="Test Cluster",
    )

    assert len(cluster.validators) == 2
    assert cluster.cluster_name == "Test Cluster"


def test_validator_cluster_validation() -> None:
    """Test that cluster validation works correctly."""
    # Test empty validators list fails
    with pytest.raises(ValueError):
        ValidatorCluster(
            cluster_id=Bytes32(b"cluster123" + b"\x00" * 22),
            validators=[],  # Empty list should fail
        )
