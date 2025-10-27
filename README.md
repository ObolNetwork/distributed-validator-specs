# Distributed Validator Specifications

Python specifications and protocol definitions for Ethereum distributed validators in the Obol network. This repository contains the core data structures, validation rules, and protocol specifications needed to implement distributed validator technology.

## Quick Start

### Prerequisites

#### Installing uv

[uv](https://github.com/astral-sh/uv) is a fast Python package manager that handles dependencies and Python versions.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
````

#### Installing Python 3.12+

This project requires Python 3.12 or later and should be installed via `uv`:

```bash
# Install Python 3.12, or latest stable version
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

## What's Included

Interoperability specs and reference models:

- Consensus (QBFT): wire protocol, message shapes, validation rules, leader/round semantics, and hashing/signing conventions
- Types and primitives: base types and helpers used by the specs
- Tests and docs: verification and documentation for implementers

### Where to start

- QBFT consensus interop: `docs/dv-spec/consensus/consensus.md`

### Project Structure

```
├── src/
│   └── dv_spec/                      # Library: specs and reference models
│       ├── __init__.py
│       ├── validator.py              # Core DV data structures (types/helpers)
│       ├── client/
│       │   ├── nodes.yaml
│       │   └── validators.yaml
│       ├── subspecs/
│       │   ├── __init__.py
│       │   └── consensus/
│       │       ├── __init__.py
│       │       ├── cryptography.py   # Placeholder for cryptographic utils
│       │       ├── qbft/             # QBFT consensus spec
│       │       │   ├── __init__.py
│       │       │   ├── definition.py
│       │       │   ├── message.py
│       │       │   ├── protocol.py
│       │       │   └── transport.py
│       │       └── timer/            # Consensus timers spec
│       │           ├── __init__.py
│       │           └── timer.py
│       └── types/                    # Ethereum-compatible base types
│           ├── __init__.py
│           ├── base.py
│           ├── basispt.py
│           ├── duty.py
│           ├── hash.py
│           ├── uint64.py
│           └── validator.py
├── tests/
│   ├── conftest.py
│   └── dv_spec/
│       ├── test_dvspec.py
│       ├── test_validator.py
│       ├── consensus/                # Consensus tests
│       │   └── ...
│       └── types/
│           └── ...
├── docs/
│   ├── index.md
│   ├── dv-spec/
│   │   └── consensus/
│   │       └── consensus.md         # QBFT interop spec
│   └── client/
│       ├── chain.md
│       ├── containers.md
│       ├── networking.md
│       └── validator.md
├── pyproject.toml
├── mkdocs.yml
└── CLAUDE.md
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

* Creates a temporary environment just for tox
* Doesn't require `uv sync` first
* Uses tox-uv for faster dependency installation

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

## Development Tools Guide

### Core Technologies
- **Pydantic models**: Type-safe data structures with automatic validation - perfect for protocol specifications
- **uv**: Ultra-fast Python package manager and project management
- **pytest**: Testing framework with excellent parametrization and fixtures
- **ruff**: Lightning-fast linter and formatter (replaces black, flake8, isort)
- **mypy**: Static type checker that works seamlessly with Pydantic

### Distributed Validator Specific
- **Ethereum Types**: Custom Uint64, Bytes32 types that match Ethereum specifications
- **Cluster Specifications**: Data structures for multi-operator validator setups
- **Protocol Validation**: Automatic validation of DV protocol constraints

### Development Workflow Tools
- **tox**: Runs tests across multiple Python versions and environments
- **mkdocs**: Documentation generator for protocol specifications
- **coverage**: Test coverage reporting to ensure thorough testing

## Common Commands Reference

| Task                                   | Command                             |
|----------------------------------------|-------------------------------------|
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

| Task                                    | Command                               |
|-----------------------------------------|---------------------------------------|
| Run all quality checks (no tests/docs)  | `uvx --with=tox-uv tox -e all-checks` |
| Run everything (checks + tests + docs)  | `uvx --with=tox-uv tox`               |
| Run specific tox environment            | `uvx --with=tox-uv tox -e lint`       |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for more guidelines.

## License

MIT License - see LICENSE file for details.
