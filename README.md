# Distributed Validator Specifications

![Obol Logo](https://obol.tech/obolnetwork.png)

## About

Python specifications and protocol definitions for Ethereum distributed validators. This repository contains the core data structures, validation rules, and protocol specifications needed to implement distributed validator technology.

## What's Included

Interoperability specs and reference models:

- **[Consensus (QBFT)](docs/dv-spec/consensus.md)**: QBFT consensus protocol for reaching agreement among distributed validator nodes
- **[Partial Signature Exchange (ParSigEx)](docs/dv-spec/parsigex.md)**: Protocol for exchanging partially signed duty data among distributed validator nodes
- **[Peer Information (PeerInfo)](docs/dv-spec/peerinfo.md)**: Protocol for exchanging node metadata and monitoring cluster health
- **[Pedersen DKG](docs/dv-spec/dkg-pedersen.md)**: Distributed key generation protocol for generating and resharing BLS validator keys
- **[DKG Sync](docs/dv-spec/dkg-sync.md)**: Synchronization protocol to coordinate distributed key generation ceremonies between nodes
- **[Reliable Broadcast](docs/dv-spec/reliable-broadcast.md)**: Two-phase signed broadcast component to prevent equivocation in DKG protocols
- **[Cluster Files](docs/dv-spec/cluster-files.md)**: File formats for cluster definition and lock files
- **[ValidatorAPI](docs/dv-spec/validatorapi.md)**: Reverse proxy and middleware layer between validator clients and beacon nodes
- **[Duty Scheduling](docs/dv-spec/duty-scheduling.md)**: Protocol for scheduling and executing beacon chain duties including slot timing and deadline calculation
- **[Priority](docs/dv-spec/priority.md)**: Protocol for achieving cluster-wide consensus on ordered preference lists
- **Types and primitives**: Base types and helpers used by the specs
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
│       ├── subspecs/                # Protocol implementations
│       │   ├── bcast/               # Reliable broadcast
│       │   ├── consensus/           # QBFT consensus
│       │   ├── dkg/                 # Pedersen DKG
│       │   ├── dkg_sync/            # DKG synchronization
│       │   ├── parsigex/            # Partial signature exchange
│       │   ├── peerinfo/            # Peer info
│       │   └── priority/            # Priority protocol
│       └── types/                   # Ethereum-compatible base types
├── tests/                           # Test suite
└── docs/
    ├── dv-spec/                     # Protocol specifications
    │   ├── cluster-files.md         # File formats for cluster definition and lock files
    │   ├── consensus.md             # QBFT consensus protocol for reaching agreement
    │   ├── dkg-pedersen.md          # Pedersen DKG for generating and resharing BLS keys
    │   ├── dkg-sync.md              # Synchronization protocol for DKG ceremonies
    │   ├── duty-scheduling.md       # Scheduling and executing beacon chain duties
    │   ├── parsigex.md              # Partial signature exchange protocol
    │   ├── peerinfo.md              # Node metadata exchange and cluster health monitoring
    │   ├── priority.md              # Cluster-wide consensus on ordered preference lists
    │   ├── reliable-broadcast.md    # Two-phase broadcast to prevent equivocation
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
| Format code                            | `uv run ruff format src tests`      |
| Lint code                              | `uv run ruff check src tests`       |
| Fix lint errors                        | `uv run ruff check --fix src tests` |
| Type check                             | `uv run mypy src tests`             |
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
