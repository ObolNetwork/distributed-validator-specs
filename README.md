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

This repository currently provides:

- **DistributedValidator**: Core specification for distributed validators with cluster metadata, operator lists, and consensus thresholds
- **ValidatorCluster**: Grouping mechanism for multiple distributed validators  
- **Ethereum Types**: Compatible base types (Uint64, Bytes32) that match Ethereum specifications
- **Validation**: Automatic Pydantic validation for all protocol constraints
- **Testing**: Comprehensive test suite with 100% coverage
- **Development Tools**: Full toolchain with linting, type checking, and documentation

### Hello World Example

```python
from dv_spec import DistributedValidator, hello_distributed_validator
from dv_spec.types import Bytes32, Uint64

# Test the basic functionality
print(hello_distributed_validator())
# Output: "Hello from the Obol Distributed Validator Network!"

# Create a basic distributed validator
dv = DistributedValidator(
    validator_index=Uint64(1),
    pubkey=Bytes32(b"validator_pubkey_32_bytes_here"),  
    cluster_id=Bytes32(b"cluster_id_32_bytes_here____"),
    operators=[Bytes32(b"operator_key_32_bytes_here___")],
    threshold=Uint64(1)
)

print(f"Created DV {dv.validator_index} with {len(dv.operators)} operators")
```

### Project Structure

```
├── src/
│   └── dv_spec/                    # Main distributed validator specs
│       ├── __init__.py             # Package exports
│       ├── validator.py            # Core DV data structures
│       ├── client/                 # Client configuration
│       │   ├── nodes.yaml          # Node configuration examples
│       │   └── validators.yaml     # Validator configuration examples
│       ├── subspecs/               # Future protocol subspecifications
│       │   └── __init__.py         # Reserved for extensions
│       └── types/                  # Base types and primitives
│           ├── __init__.py         # Type exports
│           ├── base.py             # Base Pydantic models
│           ├── hash.py             # Hash types (Bytes32, etc.)
│           ├── uint64.py           # Ethereum uint64 type
│           └── validator.py        # Validator-specific types
├── tests/                          # Test suite
│   ├── conftest.py                 # Pytest configuration
│   └── dv_spec/                    # Tests for specifications
│       ├── test_dvspec.py          # Basic package tests
│       └── test_validator.py       # Validator specification tests
├── docs/                           # MkDocs documentation
├── pyproject.toml                  # Project configuration & dependencies
└── CLAUDE.md                       # Development guide
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

## Writing Distributed Validator Specifications

### Core Concepts

This repository uses **Pydantic models** to define distributed validator data structures with automatic validation:

- **DistributedValidator**: Core specification for a DV with cluster info, operators, and thresholds
- **ValidatorCluster**: Groups of distributed validators operating together
- **Types**: Ethereum-compatible base types (Uint64, Bytes32, etc.)

### Example: Basic Distributed Validator

```python
from dv_spec import DistributedValidator, hello_distributed_validator
from dv_spec.types import Bytes32, Uint64

# Create a distributed validator specification
dv = DistributedValidator(
    validator_index=Uint64(1),
    pubkey=Bytes32(b"validator_pubkey_32_bytes_here"),
    cluster_id=Bytes32(b"cluster_id_32_bytes_here____"),
    operators=[
        Bytes32(b"operator1_pubkey_32_bytes_here"),
        Bytes32(b"operator2_pubkey_32_bytes_here"),
    ],
    threshold=Uint64(2),  # Need 2 of 2 operators for consensus
)

print(hello_distributed_validator())
print(f"DV {dv.validator_index} in cluster {dv.cluster_id.hex()[:8]}...")
```

### Example: Writing Tests

```python
# tests/dv_spec/test_my_feature.py
import pytest
from pydantic import ValidationError
from dv_spec import DistributedValidator
from dv_spec.types import Bytes32, Uint64


# Parametrized test - test multiple threshold values
@pytest.mark.parametrize("threshold", [1, 2, 5, 10])
def test_distributed_validator_threshold(threshold):
    """Test different threshold values for distributed validators."""
    operators = [Bytes32(f"operator{i}_key" + b"\x00" * 19) for i in range(threshold)]
    
    dv = DistributedValidator(
        validator_index=Uint64(1),
        pubkey=Bytes32(b"validator_pubkey" + b"\x00" * 16),
        cluster_id=Bytes32(b"cluster_id" + b"\x00" * 22),
        operators=operators,
        threshold=Uint64(threshold),
    )
    
    assert dv.threshold == threshold
    assert len(dv.operators) == threshold


# Exception testing
def test_distributed_validator_empty_operators():
    """Test that empty operators list raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        DistributedValidator(
            validator_index=Uint64(1),
            pubkey=Bytes32(b"validator_pubkey" + b"\x00" * 16),
            cluster_id=Bytes32(b"cluster_id" + b"\x00" * 22),
            operators=[],  # Empty list should fail validation
            threshold=Uint64(1),
        )
    assert "operators" in str(exc_info.value).lower()
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
