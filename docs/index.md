# Distributed Validator Specifications

This project provides reference specifications of the Obol Distributed Validator
protocol, as implemented by [Charon](https://github.com/ObolNetwork/charon) (Go)
and [Pluto](https://github.com/NethermindEth/pluto) (Rust).

## Specifications Overview

### Protocol Subspecifications

Executable protocol specifications (QBFT consensus, partial signature
exchange, DKG, peer info, priority, reliable broadcast) are located in
`src/dv_spec/subspecs/`, with accompanying documents in `docs/dv-spec/`.

### Client Subspecifications

Client specifications are located in `docs/client/`. The specs are in markdown
format for the time being and are subject to change.

## Design Principles

1. **Clarity over Performance**: Readable reference implementations
2. **Strong Typing**: Pydantic models with full validation
3. **Test Coverage**: Extensive tests for all modules
4. **Interoperability**: Precise enough for independent implementations
   (Charon, Pluto) to join the same cluster

## Development

- [Readme](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/README.md)
- [Contributing](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/CONTRIBUTING.md)
