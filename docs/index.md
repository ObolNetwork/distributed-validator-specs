# Lean Ethereum Python Specifications

This project provides reference implementations of the Lean Ethereum protocol and its
cryptographic subspecifications.

## Specifications Overview

### Lean Ethereum Specifications

The core protocol specifications are located in `src/dv_spec/`.

### Cryptographic Subspecifications

Supporting cryptographic primitives are located in `src/dv_spec/subspecs/`.

### Client Subspecifications

Client specifications are located in `docs/client/`. The specs are in markdown
format for the time being and are subject to change.

## Design Principles

1. **Clarity over Performance**: Readable reference implementations
2. **Strong Typing**: Pydantic models with full validation
3. **Test Coverage**: Extensive tests for all modules

## Development

- [Readme](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/README.md)
- [Contributing](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/CONTRIBUTING.md)
