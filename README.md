# Distributed Validator Specifications

![Obol Logo](https://obol.tech/obolnetwork.png)

## About

Python specifications and protocol definitions for Ethereum distributed validators. This repository contains the core data structures, validation rules, and protocol specifications needed to implement distributed validator technology.

The goal of these specifications is to describe the Obol distributed validator protocol precisely enough that independent implementations can interoperate within the same cluster.

## Implementations

| Client                                                    | Language | Maintainer    | Status                              |
| --------------------------------------------------------- | -------- | ------------- | ----------------------------------- |
| [Charon](https://github.com/ObolNetwork/charon)           | Go       | Obol          | Production; reference implementation |
| [Pluto](https://github.com/NethermindEth/pluto)           | Rust     | Nethermind    | In development                      |

Charon is the reference implementation these specs are derived from. Pluto is an independent implementation targeting full wire-level compatibility with Charon; these specs are the intended source of truth for that interoperability.

### Charon version anchor

These specs track Charon `main` and were last validated against Charon
commit `6054bcb2` (2026-07-29, after `v1.10.3`, during `v1.11.0` release
candidates).

The anchor is also recorded machine-readably in
[`charon_anchor.json`](charon_anchor.json), alongside the Charon paths this spec
covers. A weekly job runs
[`scripts/check_charon_drift.py`](scripts/check_charon_drift.py) to report Charon
commits past the anchor that touch those paths; run it yourself with
`uv run python scripts/check_charon_drift.py`.

Note for implementers pinned to older Charon versions (e.g. Pluto currently
targets `v1.7.1`): some specified behaviors landed after `v1.7.1`:

| Behavior | First Charon release |
| ------------------------------------------------------------------ | -------------------- |
| `MsgSync.nickname` field (DKG sync)                                 | `v1.9.0`             |
| Deterministic (genesis-derived) eager double linear round deadlines | `v1.9.0`             |
| Linear round timer subsequent-round timeout fix                     | `v1.11.0`            |
| QBFT DECIDED-resend rate limit and message size/count limits        | `v1.11.0`            |
| Preferred priority protocol ID `/charon/priority/2.0.0`             | unreleased (`main`)  |
| Stable sort of scored priorities                                    | unreleased (`main`)  |
| Sender-bound share indices in the DKG lock-hash exchange            | unreleased (`main`)  |

All of these are backwards compatible on the wire (unknown proto fields are
ignored; limits only reject messages no honest peer sends), so implementing
the current spec remains interoperable with older Charon peers.

The three unreleased entries need care in both directions. The legacy priority
protocol ID `charon/priority/2.0.0` is the **only** one every released Charon
speaks, so it must still be served alongside the preferred spelling; Charon's own
code targets `v1.12` for the preferred ID and `v1.14` for dropping the alias. The
stable sort only changes results for a tie among thirteen or more priorities in a
topic, which no released Charon produces. The sender binding rejects only
partial signatures no honest peer sends.

## What's Included

Interoperability specs and reference models:

- **[Canonical Encoding and Hashing](docs/dv-spec/hashing.md)**: Deterministic protobuf encoding and the SSZ hash root every signature and value hash is taken over
- **[Consensus (QBFT)](docs/dv-spec/consensus.md)**: QBFT consensus protocol for reaching agreement among distributed validator nodes
- **[Partial Signature Exchange (ParSigEx)](docs/dv-spec/parsigex.md)**: Protocol for exchanging partially signed duty data among distributed validator nodes
- **[Signature Aggregation (SigAgg)](docs/dv-spec/sigagg.md)**: Threshold trigger and BLS threshold aggregation of partial signatures into the group signature
- **[Peer Information (PeerInfo)](docs/dv-spec/peerinfo.md)**: Protocol for exchanging node metadata and monitoring cluster health
- **[FROST DKG](docs/dv-spec/dkg-frost.md)**: The default distributed key generation protocol for generating BLS validator keys
- **[Pedersen DKG](docs/dv-spec/dkg-pedersen.md)**: The opt-in alternative DKG algorithm, selected with `dkg_algorithm: pedersen`
- **[Cluster Edit Protocols](docs/dv-spec/dkg-cluster-edits.md)**: Reshare, add, remove and replace operators on an existing cluster
- **[DKG Sync](docs/dv-spec/dkg-sync.md)**: Synchronization protocol to coordinate distributed key generation ceremonies between nodes
- **[Reliable Broadcast](docs/dv-spec/reliable-broadcast.md)**: Two-phase signed broadcast component to prevent equivocation in DKG protocols
- **[Cluster Files](docs/dv-spec/cluster-files.md)**: File formats for cluster definition and lock files
- **[ValidatorAPI](docs/dv-spec/validatorapi.md)**: Reverse proxy and middleware layer between validator clients and beacon nodes
- **[Beacon Broadcast](docs/dv-spec/broadcast.md)**: Submitting aggregated signed duty data to the beacon node
- **[Duty Scheduling](docs/dv-spec/duty-scheduling.md)**: Protocol for scheduling and executing beacon chain duties including slot timing and deadline calculation
- **[Priority](docs/dv-spec/priority.md)**: Protocol for achieving cluster-wide consensus on ordered preference lists
- **[InfoSync](docs/dv-spec/infosync.md)**: Cluster-wide agreement on versions, protocols and proposal types; selects the consensus protocol
- **Types and primitives**: Base types and helpers used by the specs
- **[Test vectors](test_vectors/README.md)**: Conformance fixtures for implementers, most of them generated by charon itself
- **Tests and docs**: Verification and documentation for implementers

## Quick Start

### Prerequisites

[uv](https://github.com/astral-sh/uv) is a fast Python package manager that handles dependencies and Python versions.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

This project requires Python 3.12 or later. Install it via `uv`:

```bash
# Install Python 3.12 (or latest stable version)
uv python install 3.12
```

### Setup

```bash
# Clone this repository
git clone https://github.com/ObolNetwork/distributed-validator-specs distributed-validator-specs
cd distributed-validator-specs

# Install dependencies
uv sync --all-extras

# Run tests to verify setup
uv run pytest
```

### Project Structure

```
├── proto/                           # Protocol Buffer definitions
├── src/
│   └── dv_spec/                     # Library: specs and reference models
│       ├── validator.py             # Core DV data structures (types/helpers)
│       ├── client/                  # Client configuration examples
│       ├── cluster/                 # Cluster definition and lock files, and their hashes
│       ├── crypto/                  # BLS12-381 and secp256k1 signatures
│       ├── encoding/                # Deterministic proto encoding and SSZ hashing
│       ├── subspecs/                # Protocol implementations
│       │   ├── reliable_bcast/      # Reliable broadcast (charon's dkg/bcast)
│       │   ├── consensus/           # QBFT consensus
│       │   ├── dkg/                 # FROST and Pedersen DKG, node signatures
│       │   ├── dkg_sync/            # DKG synchronization
│       │   ├── infosync/            # Cluster-wide capability agreement
│       │   ├── parsigex/            # Partial signature exchange
│       │   ├── peerinfo/            # Peer info
│       │   ├── priority/            # Priority protocol
│       │   └── sigagg/              # Threshold signature aggregation
│       └── types/                   # Ethereum-compatible base types
├── scripts/                         # Test vector generation
├── test_vectors/                    # Conformance fixtures (JSON, one file per suite)
├── tests/                           # Test suite
└── docs/
    ├── dv-spec/                     # Protocol specifications
    │   ├── broadcast.md             # Submitting aggregated duty data to the beacon node
    │   ├── cluster-files.md         # File formats for cluster definition and lock files
    │   ├── consensus.md             # QBFT consensus protocol for reaching agreement
    │   ├── dkg-cluster-edits.md     # Reshare, add, remove and replace operators
    │   ├── dkg-frost.md             # FROST DKG, the default key generation algorithm
    │   ├── dkg-pedersen.md          # Pedersen DKG, the opt-in alternative algorithm
    │   ├── dkg-sync.md              # Synchronization protocol for DKG ceremonies
    │   ├── duty-scheduling.md       # Scheduling and executing beacon chain duties
    │   ├── hashing.md               # Deterministic proto encoding and SSZ hash roots
    │   ├── infosync.md              # Cluster-wide capability agreement and protocol selection
    │   ├── parsigex.md              # Partial signature exchange protocol
    │   ├── peerinfo.md              # Node metadata exchange and cluster health monitoring
    │   ├── priority.md              # Cluster-wide consensus on ordered preference lists
    │   ├── reliable-broadcast.md    # Two-phase broadcast to prevent equivocation
    │   ├── sigagg.md                # Threshold trigger and BLS threshold aggregation
    │   └── validatorapi.md          # Reverse proxy and middleware for VC-BN interaction
    └── client/                      # Additional client documentation
```

### Workspace Commands

```bash
# Install package and required dependencies or re-sync workspace
uv sync

# Install package along with all dependencies, including optional / extras
uv sync --all-extras
```

## Development Workflow

### Running Tests

```bash
# Run all tests from workspace root
uv run pytest

# Run tests in parallel
uv run pytest -n auto
```

### Code Quality

```bash
# Check code style and errors
uv run ruff check src tests

# Auto-fix issues
uv run ruff check --fix src tests

# Format code
uv run ruff format src tests

# Type checking
uv run mypy src tests
```

### Using Tox for Comprehensive Checks

After running `uv sync --all-extras`, you can use tox with `uv run`:

```bash
# Run all quality checks (lint, typecheck, spellcheck)
uv run tox -e all-checks

# Run all tox environments (all checks + tests + docs)
uv run tox

# Run specific environment
uv run tox -e lint
```

**Alternative: Using uvx (no setup required)**

If you haven't run `uv sync --all-extras` or want to use tox in isolation,
you can use `uvx`, which:

- Creates a temporary environment just for tox
- Doesn't require `uv sync` first
- Uses tox-uv for faster dependency installation

```bash
uvx --with=tox-uv tox -e all-checks
```

### Documentation

```bash
# Serve docs locally (with auto-reload)
uv run mkdocs serve

# Build docs
uv run mkdocs build
```

## Common Commands Reference

| Task                                   | Command                             |
| -------------------------------------- | ----------------------------------- |
| Install dependencies                   | `uv sync --all-extras`              |
| Run tests                              | `uv run pytest`                     |
| Format code                            | `uv run ruff format src tests scripts` |
| Lint code                              | `uv run ruff check src tests scripts` |
| Fix lint errors                        | `uv run ruff check --fix src tests scripts` |
| Type check                             | `uv run mypy src tests scripts`     |
| Regenerate test vectors                | `uv run python scripts/generate_test_vectors.py` |
| Build docs                             | `uv run mkdocs build`               |
| Serve docs                             | `uv run mkdocs serve`               |
| Run all quality checks (no tests/docs) | `uv run tox -e all-checks`          |
| Run everything (checks + tests + docs) | `uv run tox`                        |
| Run specific tox environment           | `uv run tox -e lint`                |

If you have not run `uv sync --all-extras` or want to use `tox` in isolation,
you can use `uvx`:

| Task                                   | Command                               |
| -------------------------------------- | ------------------------------------- |
| Run all quality checks (no tests/docs) | `uvx --with=tox-uv tox -e all-checks` |
| Run everything (checks + tests + docs) | `uvx --with=tox-uv tox`               |
| Run specific tox environment           | `uvx --with=tox-uv tox -e lint`       |

## Development Tools Guide

### Core Technologies

- **Pydantic models**: Type-safe data structures with automatic validation - perfect for protocol specifications
- **uv**: Ultra-fast Python package manager and project management
- **pytest**: Testing framework with excellent parametrization and fixtures
- **ruff**: Lightning-fast linter and formatter (replaces black, flake8, isort)
- **mypy**: Static type checker that works seamlessly with Pydantic

### Development Workflow Tools

- **tox**: Runs tests across multiple Python versions and environments
- **mkdocs**: Documentation generator for protocol specifications
- **coverage**: Test coverage reporting to ensure thorough testing

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for more guidelines.

## License

MIT License - see LICENSE file for details.
