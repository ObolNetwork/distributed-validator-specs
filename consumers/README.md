# Consumer suites

Test code that runs the [published vectors](../test_vectors/README.md) against a
real implementation. The vectors only prove something once an implementation
executes them: a suite nobody runs is a document, not a test.

| Consumer | Status | Location |
| --------------------------------- | ---------------------------------------------- | ----------- |
| Charon (Go) | All 9 suites, 314 subtests, verified at anchor `6054bcb2` | [`go/`](go) |
| Pluto (Rust) | Not written yet | — |

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
