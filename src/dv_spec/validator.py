"""Basic distributed validator specification."""

from typing import List, Optional

from pydantic import Field

from dv_spec.types import Bytes32, StrictBaseModel, Uint64


class DistributedValidator(StrictBaseModel):
    """A distributed validator specification.

    This represents a validator that operates in a distributed manner
    across multiple nodes in the Obol network.
    """

    validator_index: Uint64 = Field(description="The validator index in the beacon chain")

    pubkey: Bytes32 = Field(description="The validator's public key")

    cluster_id: Bytes32 = Field(
        description="Unique identifier for the distributed validator cluster"
    )

    operators: List[Bytes32] = Field(
        description="List of operator node public keys in this cluster",
        min_length=1,
        max_length=10,
    )

    threshold: Uint64 = Field(description="Minimum number of operators required for consensus")

    active: bool = Field(
        default=True, description="Whether this distributed validator is currently active"
    )

    version: str = Field(
        default="1.0.0", description="Version of the distributed validator specification"
    )


class ValidatorCluster(StrictBaseModel):
    """A cluster of distributed validators."""

    cluster_id: Bytes32 = Field(description="Unique identifier for this cluster")

    validators: List[DistributedValidator] = Field(
        description="List of validators in this cluster",
        min_length=1,
    )

    cluster_name: Optional[str] = Field(
        default=None, description="Human-readable name for this cluster"
    )


def hello_distributed_validator() -> str:
    """Hello world function for distributed validator specs.

    Returns:
        A greeting message from the distributed validator system.
    """
    return "Hello from the Obol Distributed Validator Network!"
