# Consumer suites

Test code that runs the [published vectors](../test_vectors/README.md) against a
real implementation. The vectors only prove something once an implementation
executes them: a suite nobody runs is a document, not a test.

| Consumer | Status | Location |
| --------------------------------- | ---------------------------------------------- | ----------- |
| Charon (Go) | All 9 suites, 314 subtests, verified at anchor `6054bcb2` | [`go/`](go) |
| Pluto (Rust) | All 9 suites checked against pluto `67088a2` — 2 FAIL (`qbft_hashing`, `cluster_hashing`), rest PASS, ABSENT-OK, or UNREACHABLE; see plans/pluto-conformance.md | [rust/](rust) |

These files live here rather than in Charon because this repository cannot merge
into Charon. They are laid out to mirror Charon's own tree, so placing them is a
copy rather than a set of instructions:

```bash
rsync -a consumers/go/ ~/charon/
```

## Why it is not one test package

Most of what the vectors cover is unexported in Charon. `hashProto`,
`verifyMsgLimits`, `verifyPeerShareIdx`, `calculateResult`, the round timer
helpers and the decided-resend limiter are all package-private, so an external
test package physically cannot reach them. The suite is therefore one importable
loader plus in-package test files:

| File | Package | Suites |
| ----------------------------------------------------- | ---------------------- | ------ |
| `testutil/specvectors/specvectors.go` | loader (importable) | — |
| `testutil/specvectors/vectors_test.go` | external | `cluster_hashing`, `bls_threshold`, `secp256k1_signatures` |
| `core/consensus/qbft/spec_vectors_internal_test.go` | `qbft` | `qbft_hashing` (duty, data sets, signing roots), `qbft_msg_limits` |
| `core/priority/spec_vectors_internal_test.go` | `priority` | `qbft_hashing` (`any_string`), `priority_scoring` |
| `dkg/spec_vectors_internal_test.go` | `dkg` | `parsigex_sender_binding` |
| `core/consensus/timer/spec_vectors_internal_test.go` | `timer` | `timer_deadlines` |
| `core/qbft/spec_vectors_internal_test.go` | `qbft` (core) | `qbft_decided_resends` |

`specvectors.CoveredSuites` records that mapping in code, and
`TestEverySuiteIsCovered` fails when a spec release ships a suite nothing runs —
an uncovered suite is otherwise indistinguishable from a passing one.

## The two `hashProto`s are not interchangeable

Charon has two functions of that name with **different semantics for `Any`**:

- `core/priority` hashes the `Any` wrapper itself, type URL included
  (`calculate.go` hashes `topic.GetTopic()` directly).
- `core/consensus/qbft` refuses an `Any` outright and the caller unwraps first,
  so the hash covers the inner message.

That is why the `any_string` cases are tested in `core/priority` and not
alongside the other `qbft_hashing` groups: handing them to the consensus hasher
returns "cannot hash any proto, must hash inner value". An implementation with a
single Any-hashing convention will diverge on one side or the other.

## Running it

The artifact is vendored, so the tests need no network:

```bash
# From a spec checkout: build the release and vendor it into charon.
uv run python scripts/build_release.py
mkdir -p ~/charon/testdata/spec && cp -r dist/spec-v0.1.0/* ~/charon/testdata/spec/

rsync -a consumers/go/ ~/charon/
cd ~/charon && go test ./testutil/specvectors/ ./core/consensus/qbft/ \
  ./core/priority/ ./dkg/ ./core/consensus/timer/ ./core/qbft/ -run 'TestSpec|TestManifest|TestEverySuite|TestCluster|TestBLS|TestSecp'
```

`SPEC_VECTORS_DIR` overrides the vendored location, for running against an
unreleased build without re-vendoring.

`specvectors.PinnedSpecVersion` must match the vendored `manifest.json`. Vendoring
a different release without updating the constant would quietly change what Charon
is being held to, so the loader refuses to run.

## What a failure means

These are not fixtures of Charon's current output. Most expected values were
produced by Charon and then published, so a failure means Charon has moved away
from the protocol every other implementation was told to implement. The
regeneration path is deliberately not automatic — see the spec's
`test_vectors/README.md`.

## Pluto consumer

`rust/` is a standalone Cargo package that path-depends on a pluto checkout
placed as a sibling of this repository (`../pluto` relative to
`distributed-validator-specs/`, i.e. `../../../pluto` from `consumers/rust/`).
Unlike the Go consumer, nothing is copied into pluto and pluto is never
modified — the harness reads pluto's crates in place.

### Running it

```bash
# pluto checked out as a sibling of this repo (default: ../pluto)
cd consumers/rust && cargo test
```

Vectors are read from `../../test_vectors/` at test time (no vendoring), or
from `SPEC_VECTORS_DIR` when set (same variable as the Go consumer), for
running against an unreleased build without moving files around.

### Verdicts

All nine published suites were run against pluto commit `67088a2`. This is a
snapshot of one pluto commit, not a continuously tracked target: `PASS` means
pluto reproduced every case the vector covers at that commit; `ABSENT-OK` and
`UNREACHABLE` are not passes — they record, respectively, a divergence excused
by pluto's charon-v1.7.1 parity pin, and a coverage gap where no public pluto
API reaches the behaviour at all. Full per-case detail, findings, and pluto
file:line citations are in `plans/pluto-conformance.md`'s Results table and
Findings section.

| Suite | Verdict |
| --- | --- |
| `secp256k1_signatures` | PASS (2/2) |
| `qbft_hashing` | **FAIL** — 23/25 cases agree; 2 pinned divergences (prost omits default-valued protobuf map-entry key/value fields that charon's Go marshaler always emits) |
| `bls_threshold` | PASS (all 5 groups) |
| `cluster_hashing` | **FAIL** — pluto rejects charon-legitimate JSON shapes (`operators: null`, an absent `partial_deposit_data`, and a masked third gap on `timestamp`) |
| `priority_scoring` | PASS (18/18) |
| `timer_deadlines` | `round_timeout_nanos` PASS **only with `ProposalTimeout` explicitly enabled** (9 PROPOSER/round-1 cases diverge under pluto's default config — ABSENT-OK, ladder entry "Extended 1.5s proposer round-1 timeout (proposal_timeout)"); `deadline_nanos` ABSENT-OK; `duty_start_delay_nanos` UNREACHABLE |
| `qbft_msg_limits` | `counts`: 5 MATCH + 6 ABSENT-OK; `wire_size`: 4/4 MATCH |
| `qbft_decided_resends` | ABSENT-OK (pluto has no DECIDED-rebroadcast limiter) |
| `parsigex_sender_binding` | `cases` ABSENT-OK; `peer_map` UNREACHABLE |
