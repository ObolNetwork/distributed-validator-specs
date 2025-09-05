# Working with distributed-validator-specs

## Repository Overview

This is a Python repository for Ethereum Distributed Validator protocol specifications. It is set up as
a single `uv` project containing the main specifications, data structures, and validation rules
for distributed validator clusters in the Obol network.

## Key Directories

- `src/dv_spec/` - Main distributed validator specifications and data structures
- `src/dv_spec/subspecs/` - Reserved for future protocol subspecifications
- `src/dv_spec/types/` - Ethereum-compatible base types (Uint64, Bytes32, etc.)
- `src/dv_spec/client/` - Client configuration examples
- `tests/` - Specification tests
- `docs/` - MkDocs documentation source

## Development Workflow

### Running Tests
```bash
# Sync all dependencies and install packages
uv sync --all-extras

# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src/dv_spec --cov-report=html
```

### Code Quality Checks
```bash
# Format code
uv run ruff format src tests

# Check linting
uv run ruff check src tests

# Fix fixable linting errors
uv run ruff check --fix src tests

# Type checking
uv run mypy src tests

# Run all quality checks (lint, typecheck, spellcheck)
uv run tox -e all-checks

# Run everything (all checks + tests + docs)
uv run tox
```

### Common Tasks

1. **Adding to main specs**: Located in `src/dv_spec/` (e.g., new validator types, cluster specs)
2. **Adding base types**: Located in `src/dv_spec/types/` (e.g., new Ethereum-compatible types)
3. **Adding to subspecs**: Located in `src/dv_spec/subspecs/` (future protocol extensions)
   - Create a new subdirectory for each subspec (e.g., `src/dv_spec/subspecs/consensus/`)
   - Tests for subspecs should be in `tests/dv_spec/subspecs/{subspec}/`, mirroring the source structure

## Important Patterns

### Test Patterns
- Tests should be placed in `tests/` and follow the same structure as the source code.
- Use `pytest.fixture`, in `conftest.py` or test files, for reusable test setup.
- Use `pytest.mark.parametrize` to parametrize tests with multiple inputs
- Use `pytest.raises(...)` with specific exceptions to test error cases
- Use `@pytest.mark.slow` for long-running tests

## Code Style

- Line length: 79 characters
- Use type hints everywhere
- Follow Google docstring style
- No docstrings needed for `__init__` methods
- Imports are automatically sorted by `isort` and `ruff`

## Testing Philosophy

- Tests should be simple and clear
- Test file names must start with `test_`
- Test function names must start with `test_`
- Use descriptive test names that explain what's being tested

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

## Important Notes

1. This repository uses Python 3.12+ features
2. All models should use Pydantic for automatic validation.
3. Keep things simple, readable, and clear. These are meant to be clear specifications.
4. The repository is `distributed-validator-specs` for Obol's distributed validator protocol.
5. Focus on distributed validator cluster specifications, operator management, and consensus thresholds.
