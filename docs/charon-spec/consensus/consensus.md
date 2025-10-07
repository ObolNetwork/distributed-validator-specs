# QBFT Consensus Protocol

## Overview

The distributed validator consensus layer uses **QBFT**. It ensures that all honest nodes in a distributed validator cluster agree on the same value despite up to f Byzantine (malicious or faulty) nodes, where f < n/3.

## Threat Model

QBFT tolerates up to f Byzantine nodes in a cluster of n = 3f+1 nodes:

- **4 nodes**: tolerates 1 Byzantine node
- **7 nodes**: tolerates 2 Byzantine nodes
- **10 nodes**: tolerates 3 Byzantine nodes

Byzantine nodes may:

- Send invalid or conflicting messages
- Refuse to participate
- Collude with other Byzantine nodes

Byzantine nodes cannot:

- Break cryptographic signatures
- Compromise more than f nodes

## Core Concepts

### Duties

A **duty** represents a specific validator task at a particular slot. All consensus messages are scoped to a single duty. Examples:

- Attesting at slot 1234
- Proposing at slot 1235
- Sync committee contribution at slot 1236

### Consensus

The consensus protocol described in this document is **QBFT**. This protocol proceeds in rounds, with each round having a designated leader who proposes a value. Nodes vote on the proposal through prepare and commit phases. If consensus is not reached within a timeout, nodes move to the next round with a new leader.

### Rounds

Rounds start from 1 (1, 2, 3, ...). Each round has a deterministic leader:

```
leader_index = (duty.slot + duty.type + round) % cluster_size

- duty.slot: Current Ethereum slot number
- duty.type: Integer representing the duty type (e.g., 0 for attestation, 1 for proposal)
- round: Current QBFT round number
- cluster_size: Total number of nodes in the DV cluster
- leader_index: Index of the peer array (0 to cluster_size-1)
```

### Timeouts

Moving between rounds is governed by a timeout mechanism. Each round has a timer that starts when the round begins. If consensus is not reached before the timer expires, nodes move to the next round.

There are different timer implementations. The default is a double-eager linear timer.
They can be found [here](/src/dv_spec/subspecs/consensus/qbft/timer.py).

### Phases

Each round has three phases:

1. **Pre-Prepare**: Leader proposes a value
2. **Prepare**: Nodes vote on the proposal
3. **Commit**: Nodes commit to the agreed value

These phases are modeled as `UponRule` events in [here](/src/dv_spec/subspecs/consensus/qbft/protocol.py).
```python
class UponRule(Enum):
    """UponRule defines the event based rules that are triggered when messages are received."""
    NOTHING = "nothing"
    JUSTIFIED_PRE_PREPARE = "justified_pre_prepare"
    QUORUM_PREPARES = "quorum_prepares"
    QUORUM_COMMITS = "quorum_commits"
    UNJUST_QUORUM_ROUND_CHANGES = "unjust_quorum_round_changes"
    F_PLUS_1_ROUND_CHANGES = "f_plus_1_round_changes"
    QUORUM_ROUND_CHANGES = "quorum_round_changes"
    JUSTIFIED_DECIDED = "justified_decided"
    ROUND_TIMEOUT = "round_timeout"
```

Upon receiving messages, the protocol evaluates them and triggers the appropriate `UponRule` to handle state transitions and actions.

### Message Formats


Peer exchanges message using protobufs over libp2p. The equivalent Python data models are defined [here](/src/dv_spec/subspecs/consensus/qbft/message.py).

There are five different message types:
```python
class MsgType(IntEnum):
    """QBFT message types."""
    PRE_PREPARE = 1
    PREPARE = 2
    COMMIT = 3
    ROUND_CHANGE = 4
    DECIDED = 5
```

Every message type is encapsulated in a single `QBFTMessage` envelope:
```python
class QBFTMsg(BaseModel):
    """A message in the QBFT consensus protocol."""
    type: MsgType = Field(description="The type of QBFT message.")
    duty: Duty = Field(description="The duty associated with the message.")
    peer_idx: int = Field(description="The index of the peer sending the message.")
    round: int = Field(description="The round number for the message.")
    prepared_round: Optional[int] = Field(
        default=None,
        description="The prepared round number. None indicates no preparation has occurred."
    )
    signature: Optional[bytes] = Field(default=None, description="The signature of the message.")
    value_hash: Optional[bytes] = Field(default=None, description="The hash of the value being proposed.")
    prepared_value_hash: Optional[bytes] = Field(
        default=None,
        description="The hash of the prepared value."
    )
```

This message is then encapsulated in a `QBFTConsensusMsg` which carries additional data such as `justification` and `values`:
```python
class QBFTConsensusMsg(BaseModel):
    """A consensus message containing a QBFT message and its justifications."""
    msg: QBFTMsg = Field(description="The main QBFT message being sent.")
    justification: list[QBFTMsg] = Field(
        default_factory=list,
        description="Supporting messages proving validity of this message"
    )
    values: list[Any] = Field(
        default_factory=list,
        description="Actual consensus values referenced by value hashes"
    )
```

`justification` contains previously received messages that justify the current message. For example, a prepared `ROUND_CHANGE` message may be justified by a quorum of `PREPARE` messages. This logic is described in [here](/src/dv_spec/subspecs/consensus/qbft/protocol.py).

# TODO is this true ?
`values` contains the actual consensus values referenced by their hashes in the messages. This allows nodes to exchange only hashes in the main messages, reducing bandwidth, while still being able to provide the full values when necessary.

### Consensus State

The main consensus state machine that handles message processing and state transitions is defined in the `QBFTConsensus` class [here](/src/dv_spec/subspecs/consensus/qbft/protocol.py).

```python
@dataclass
class QBFTConsensus:
    """
    QBFT consensus instance for a specific duty.

    Maintains all data needed for QBFT consensus including message history,
    state information, and timing for round changes.
    """

    d: QBFTDefinition
    """QBFT system parameters."""

    duty: Duty
    """Current duty being agreed upon."""

    peer: int
    """Index of this peer in the cluster."""

    proposal_value: Any
    """Proposal value for this node."""

    round: int = 1
    """Current round number."""

    prepared_round: Optional[int] = None
    """Prepared round if any."""

    prepared_value: Optional[Any] = None
    """Prepared value if any."""

    prepared_value_hash: Optional[bytes] = None
    """Hash of the prepared value if any."""

    prepared_justification: List[QBFTMsg] = field(default_factory=list)
    """Justification for the prepared value if any."""

    q_commit: List[QBFTMsg] = field(default_factory=list)
    """Stored quorum of COMMIT messages."""

    buffer: Dict[int, List[QBFTConsensusMsg]] = field(default_factory=dict)
    """Storer for peer messages."""

    dedupRules: Dict[Tuple[UponRule, int], bool] = field(default_factory=dict)
    """Deduplication for rules triggered per round."""

    round_start_time: float = field(default_factory=time.time)
    """Timestamp when the current round started."""

    timer: RoundTimer = field(init=False)
    """Round timer instance."""

    # TODO Charon works a bit differently than this
    mapping: Dict[bytes, Any] = field(default_factory=dict)
    """Stores value mappings by their hash."""
```


## Testing and Verification

The specification includes comprehensive tests:

- Message validation: `tests/dv_spec/consensus/test_messages.py`
- Protocol logic: `tests/dv_spec/consensus/test_protocol.py`
- Timer implementations: `tests/dv_spec/consensus/test_timer.py`

Run tests:

```bash
uv run pytest tests/dv_spec/consensus/ -v
```