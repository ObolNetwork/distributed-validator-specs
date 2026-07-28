# Test vectors

Conformance fixtures for implementations of the Obol Distributed Validator
protocol. Each suite is one JSON file, checked in, and consumed directly — there
is no build step and no code generation.

The point of these files is to be a source of truth that is independent of any
one implementation. Where a value could be obtained from Charon, it was, so that
a passing suite means "agrees with Charon" rather than "agrees with this spec".

## Suites

| File                        | Covers                                                                                              | Source  |
| --------------------------- | --------------------------------------------------------------------------------------------------- | ------- |
| `qbft_hashing.json`         | Deterministic protobuf encodings and SSZ hash roots: duties, consensus values, QBFT signing roots, `Any`-wrapped strings | charon  |
| `bls_threshold.json`        | BLS12-381 keys, partial signatures, threshold (Lagrange) and plain aggregation                       | charon  |
| `secp256k1_signatures.json` | 65-byte `R \|\| S \|\| V` signatures and public key recovery                                        | charon  |
| `priority_scoring.json`     | Cluster-wide priority results from per-peer preference orders                                        | charon  |
| `timer_deadlines.json`      | Consensus round deadlines by genesis, slot duration, slot, duty type and round                      | spec    |

The suites chain where the protocol does: the digest signed in
`secp256k1_signatures.json` is the QBFT signing root derived in
`qbft_hashing.json`, so an implementation that gets the encoding wrong fails at
the signature too.

## File format

Every suite is an object with:

- `suite` — must equal the filename without its extension.
- `description` — what the suite covers, and any formula needed to interpret it.
- `provenance` — `source` (`charon` or `spec`), `charon_ref` (the commit the
  suite was validated against), `generated_by`, and a `note` explaining how the
  values were obtained.
- One or more arrays of cases. `timer_deadlines` and `priority_scoring` use a
  single `cases` array; `qbft_hashing` groups its cases by message type
  (`duty`, `unsigned_data_set`, `qbft_signing_root`, `any_string`).

Every case has a `name` unique within its array, an `input` object, and the
expected outputs as sibling keys. Byte strings are lower-case hex without a `0x`
prefix. Some cases carry a `notes` field explaining the rule they pin down —
those are the cases most likely to catch a bug, so start there when debugging.

## Provenance

`source: charon` means the expected values came out of Charon, not out of this
spec:

- `qbft_hashing.json` was produced by `charon/hashproto_generator/main.go`, which
  copies Charon's `hashProto` verbatim and calls Go's
  `proto.MarshalOptions{Deterministic: true}`.
- `bls_threshold.json` and `secp256k1_signatures.json` were produced by
  `charon/crypto_generator/main.go`, calling Charon's `tbls` and `app/k1util`
  packages. The BLS key shares are spec-chosen inputs; everything derived from
  them — public shares, signatures, aggregates — is Charon's output. Charon's
  `RecoverSecret` over shares 1–3 returning the group secret is what confirms
  the sharing is valid and that secret keys are big-endian.

- `priority_scoring.json` expectations are transcribed from Charon's
  `core/priority/calculate_internal_test.go` `TestCalculateResults` table.
  `scripts/generate_test_vectors.py` fails if this spec does not reproduce them.

To reproduce a Go-generated suite: copy the generator's directory into a Charon
checkout at the `charon_ref` commit as `zz_spec_vectors/`, run
`go run ./zz_spec_vectors`, and compare. Each generator lives in its own
directory because both are `package main`; side by side in one directory they
would not compile.

`source: spec` means this spec computed the values from its reading of Charon's
source. `timer_deadlines.json` is in this category: the deadlines are plain
arithmetic, but no Charon test exposes them as a table.

## Regenerating

```bash
uv run python scripts/generate_test_vectors.py
```

This rewrites the `source: spec` suites and re-checks `priority_scoring.json`
against Charon's table. It deliberately does not touch `qbft_hashing.json`,
which requires a Go toolchain and a Charon checkout — see above.

`tests/test_vectors.py` runs every suite against the spec, so a suite that
drifts from the implementation fails the normal test run.

## Units and precision

`timer_deadlines.json` is expressed in integer nanoseconds, and those integers
are normative. Charon computes deadlines with `time.Duration`, so the slot
fraction for attester and aggregator duties is an integer division: a 5s slot
gives an attester delay of 1666666666ns. A float cannot hold a unix timestamp to
nanosecond resolution, so an implementation that compares deadlines exactly must
use integers.
