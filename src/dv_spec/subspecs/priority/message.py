"""Priority protocol message definitions.

The Priority component exchanges prioritized lists of arbitrary data among
distributed validator nodes. Each node broadcasts its priorities to all peers,
who respond with their own priorities. A deterministic calculation produces
cluster-wide agreed-upon priorities ordered by peer count and position.

This module is transport-agnostic and only defines data models for the over-
the-wire message structures.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from dv_spec.types.duty import Duty


class PriorityTopicProposal(BaseModel):
    """A proposed priority list for a single topic.

    Contains a topic identifier and an ordered list of priorities
    for that topic.
    """

    topic: Any = Field(description="Topic identifier (typically string)")
    priorities: list[Any] = Field(
        default_factory=list,
        description="Ordered list of priorities (typically strings, ordered by preference)",
    )


class PriorityMsg(BaseModel):
    """Priority message exchanged between peers.

    Contains a node's proposed priorities for one or more topics
    for a given duty, along with cryptographic signature.
    """

    duty: Duty = Field(description="The validator duty instance")
    peer_id: str = Field(description="libp2p peer ID string of the sender")
    topics: list[PriorityTopicProposal] = Field(
        default_factory=list, description="List of topic proposals with priorities"
    )
    signature: bytes = Field(
        default=b"", description="secp256k1 signature over message hash (empty before signing)"
    )


class PriorityScoredResult(BaseModel):
    """A single priority with its calculated score.

    Represents one priority value along with its cluster-wide score
    calculated from peer count and position.
    """

    priority: Any = Field(description="Priority value (typically string)")
    score: int = Field(description="Calculated score (count_weight * peer_count + position_scores)")


class PriorityTopicResult(BaseModel):
    """Cluster-wide priority results for a single topic.

    Contains the topic identifier and the list of priorities
    ordered by their calculated scores.
    """

    topic: Any = Field(description="Topic identifier (typically string)")
    priorities: list[PriorityScoredResult] = Field(
        default_factory=list, description="Priorities ordered by score (descending)"
    )


class PriorityResult(BaseModel):
    """Complete priority protocol result.

    Contains all input messages and the calculated cluster-wide
    priority results for all topics.
    """

    msgs: list[PriorityMsg] = Field(
        default_factory=list, description="All input messages used to calculate result"
    )
    topics: list[PriorityTopicResult] = Field(
        default_factory=list, description="Calculated results for each topic"
    )
