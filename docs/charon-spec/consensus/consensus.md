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

### Rounds

Consensus proceeds in numbered **rounds** starting from 1 (1, 2, 3, ...). Each round has a deterministic leader:

```
leader_index = (duty.slot + duty.type + round) % cluster_size
```

Round 1 is the initial round. If consensus is not reached (timeout), nodes move to round 2, and so on. 

### Phases

Each round has three phases:

1. **Pre-Prepare**: Leader proposes a value
2. **Prepare**: Nodes vote on the proposal
3. **Commit**: Nodes commit to the agreed value

## Message Formats

### Core Message Types

```python
class MsgType(IntEnum):
    PRE_PREPARE = 1
    PREPARE = 2
    COMMIT = 3
    ROUND_CHANGE = 4
    DECIDED = 5

class QBFTMsg(BaseModel):
    type: MsgType
    duty: Duty
    peer_idx: int
    round: int  # >= 1
    prepared_round: Optional[int] = None
    signature: bytes  # 65 bytes
    value_hash: bytes  # 32 bytes
    prepared_value_hash: Optional[bytes] = None

class QBFTConsensusMsg(BaseModel):
    msg: QBFTMsg
    justification: list[QBFTMsg] = []
    values: list[Any] = []  # Actual consensus values
```

## Implementation Reference

The canonical specification is in Python:

- Message definitions: `src/dv_spec/subspecs/consensus/qbft/message.py`
- Protocol logic: `src/dv_spec/subspecs/consensus/qbft/protocol.py`
- Timer implementations: `src/dv_spec/subspecs/consensus/timer/timer.py`

## Architecture and Components

### QBFTConsensus Class

The main consensus state machine that handles message processing and state transitions:

```python
@dataclass
class QBFTConsensus:
    duty: Duty
    cluster_size: int
    peer_idx: int
    current_round: int = 1  # Protocol starts at round 1

    # Byzantine fault tolerance properties
    max_byzantine_faults: int  # floor((n-1)/3)
    quorum_size: int          # ceil(2*n/3)

    # Timer for round changes
    timer: RoundTimer = DoubleEagerLinearRoundTimer()
```

### Upon Rules System

The protocol uses an "upon rules" system for deterministic message processing:

```python
class UponRule(Enum):
    JUSTIFIED_PRE_PREPARE = "justified_pre_prepare"
    QUORUM_PREPARES = "quorum_prepares"
    QUORUM_COMMITS = "quorum_commits"
    F_PLUS_1_ROUND_CHANGES = "f_plus_1_round_changes"
    ROUND_TIMEOUT = "round_timeout"
    # ...
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