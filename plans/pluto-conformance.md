# Pluto Conformance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Rust test harness in this repo (`consumers/rust/`) that runs every published
vector suite against an unmodified pluto checkout, so a spec-repo user can test the
current pluto implementation independently — the mirror of `consumers/go/` for charon,
but inverted: nothing is copied into pluto, the harness path-depends on pluto's crates.

**Architecture:** One standalone Cargo package outside pluto's workspace, with
`path = "../../../pluto/crates/…"` dependencies (sibling-checkout convention, like
`~/charon` for the Go consumer). Vectors are read from `../../test_vectors/` at test
time — no vendoring, no build step. Each suite gets one integration-test file; each
case gets a named subcheck. One suite per task, run and triaged before the next starts.

**Tech Stack:** Rust 1.95.0 (pluto's pin), edition 2024, `serde_json` for loading,
pluto crates as path dependencies, `tokio` with `start_paused` for timer checks.

## Why this is not a normal feature plan

A conformance check does not "pass or get fixed" — it produces a **verdict**, and a
red case is a *finding to record*, never a reason to weaken the assertion. Pluto pins
parity to **charon v1.7.1**, while the vectors describe charon main at `6054bcb2`.
`charon_anchor.json` → `behaviours` lists exactly which specified behaviours postdate
v1.7.1. Verdict taxonomy, used in the Results table below:

| Verdict | Meaning |
| --- | --- |
| `PASS` | Pluto reproduces every case in the group. |
| `FAIL` | Pluto diverges and no ladder entry excuses it — a real finding; record it under Findings and consider reporting upstream to pluto. |
| `ABSENT-OK` | Divergence matches a `behaviours` entry with `first_charon_release` > v1.7.1 (or `null`). The test then **pins pluto's current behaviour** with a comment naming the ladder entry, so it flips loudly when pluto catches up. |
| `UNREACHABLE` | No public API path from an external crate; verified by code inspection instead, with file:line recorded. A coverage gap, not a pass. |

## Pre-registered expectations (verify, don't assume)

Found by reading pluto at `67088a2` before writing any test. Each must be confirmed
or refuted by the task that covers it:

1. Justification cap is `4 * nodes` (`MAX_JUSTIFICATIONS_PER_NODE = 4`,
   `crates/consensus/src/qbft/component.rs:42`) — not the spec's `2n`. Ladder entry
   "QBFT DECIDED-resend rate limit and message size/count limits" (`null`) covers the
   spec's `2n` being absent, but a *third* value (neither charon v1.7.1's no-cap nor
   the spec's `2n`) is a finding worth recording regardless.
2. No `values ≤ 2(j+1)` check exists anywhere in pluto. Same ladder entry.
3. `MAX_CONSENSUS_MSG_SIZE = 32 MiB` **is** implemented (`qbft/p2p.rs`) despite being
   part of the same `null` ladder entry — the wire-size half may genuinely PASS.
4. No DECIDED-resend limiter (`crates/core/src/qbft/mod.rs:494-503` rebroadcasts
   unboundedly). Ladder: same `null` entry → ABSENT-OK expected.
5. No ParSigEx/DKG sender binding (no `share_idx == sender` check found). Ladder:
   "Sender-bound share indices in the DKG lock-hash exchange" (`null`).
6. Priority protocol ID is the slash-less `charon/priority/2.0.0` only. Ladder:
   "Preferred priority protocol ID" (`null`) — legacy-only is correct for v1.7.1.
7. Round timers are relative (`RoundTimer::timer` measures from now); genesis-derived
   deterministic deadlines are the v1.9.0 ladder entry → `deadline_nanos` likely
   ABSENT-OK. `linear_subsequent_round_timeout` reproduces charon v1.7.1's
   nanosecond bug (200ns, ObolNetwork/charon#4537); the vectors encode the *fixed*
   behaviour (ladder entry "Linear round timer subsequent-round timeout fix", `null`).

## Results

Progress tracking lives here. Update the row when a task's verdict is in; record the
pluto commit actually tested. Statuses: `todo` / `in progress` / `done`.

**Pluto commit under test:** `67088a2`

| # | Check | Suite | Status | Verdict | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Harness scaffold + secp256k1 | `secp256k1_signatures` | done | PASS | Both cases pass: sign, recover, and verify_65 all match the vector via `pluto-k1util` (33-byte SEC1 pubkey). |
| 2 | Proto encoding + SSZ hashing | `qbft_hashing` | done | FAIL (unsigned_data_set only) | `duty` (3/3), `qbft_signing_root` (6/6), `any_string` (4/4) all PASS. `unsigned_data_set` has 10/12 strict-PASS; `empty_value` and `empty_key` are a real divergence, no ladder entry: prost's map encoding applies proto3 default-value omission *inside* map entries (skips an empty string key or empty bytes value), while charon's Go marshaler always writes both map-entry fields explicitly. See Findings. Pinned as a named known-divergence test (`unsigned_data_set_known_divergence_empty_map_entry_fields`) rather than left permanently red, so a future regression in the other 10 cases can't hide behind it; that test fails loudly if pluto's output ever changes (fixed or otherwise). Pluto's own `crates/consensus/testdata/vectors/hashproto.json` never exercises an empty key/value entry, so this suite gives it strictly broader coverage — a candidate for pluto to adopt these vectors and retire its own file, not something this repo changes. |
| 3 | BLS threshold aggregation | `bls_threshold` | done | PASS | All 5 groups PASS: `keys` (2/2), `partials` (4/4, pubshare + partial signature), `threshold_aggregates` (4/4 distinct 3-of-4 quorums, each reproducing the one `group_signature_hex`), `recovery` (1/1, `recover_secret` yields the exact `group_secret_hex`), `plain_aggregate` (1/1, matches the pinned bytes and does **not** verify under `group_pubkey_hex`, confirming plain aggregation is not a threshold-signature substitute). `group_signature_hex` also verifies under `group_pubkey_hex`. `pluto-crypto`'s `BlstImpl`/`Tbls` API matched the brief's guesses exactly; no divergence found. |
| 4 | Cluster hashes + lock verification | `cluster_hashing` | done | FAIL (2 pinned known-divergence cases; at least 3 distinct affected fields — a lower bound, not a total) | `definition` 5/6 strict-PASS (`config_hash` and `definition_hash` both match on 5 cases, including the unsigned/signed pair proving config_hash is signature-independent); `all_empty_lists` is a real divergence, pinned (see Findings) — it carries **at least two independent parse blockers** (`operators`/`validators` null-rejection, then a masked `timestamp` missing-field rejection once the first is hypothetically fixed), so a partial upstream fix will not make it pass. `lock` 3/4 strict-PASS (`lock_hash` matches and `verify_hashes` succeeds on 3); `validator_without_deposit_data` is a second real divergence, pinned (see Findings). `real_keys_3_of_4`: hashes verify; the full `verify_signatures(&EthClient::new(""))` chain is asserted to fail specifically at the definition EIP-712 stage (`LockError::DefinitionSignaturesVerificationFailed`) because its operator/creator signatures are unavoidable placeholders (charon's EIP-712 signing helpers aren't exported for vector generation) — `Lock::verify_signatures` short-circuits there, so its private BLS-aggregate and node-signature checks are never reached from this external crate; that half is a coverage gap (not a failure), noted in the test's doc comment rather than mocked around. |
| 5 | Priority scoring | `priority_scoring` | todo | — | |
| 6 | Round timer deadlines | `timer_deadlines` | todo | — | |
| 7 | QBFT message limits | `qbft_msg_limits` | todo | — | |
| 8 | DECIDED-resend limiting | `qbft_decided_resends` | todo | — | |
| 9 | Sender binding + peer map | `parsigex_sender_binding` | todo | — | |
| 10 | Coverage guard + docs | all | todo | — | |

## Findings

_Append findings here as tasks produce them: what diverged, file:line in pluto,
whether a ladder entry covers it, and whether it was reported upstream._

- **`UnsignedDataSet` map entries with an empty key or empty value hash differently
  than charon (FAIL, task 2, `qbft_hashing/unsigned_data_set`).** prost's generated
  `btree_map` encoding (`pluto_core::corepb::v1::UnsignedDataSet.set`, a
  `BTreeMap<String, Bytes>`) skips a map entry's key field when it equals `""` and
  skips its value field when it equals `b""` — proto3 default-value omission applied
  to the two synthetic fields of each map entry
  (prost 0.14.4, `encoding::encode_with_default`). Charon's
  `hashProto`, built on Go's `google.golang.org/protobuf`, always writes both map-entry
  fields regardless of default-ness. Confirmed by two vectors:
  `empty_value` (`set: {"0xaabb": ""}`) encodes to `0a0a0a063078616162621200` per
  charon but `0a080a06307861616262` per pluto (missing the empty-value field 2);
  `empty_key` (`set: {"": "01"}`) encodes to `0a050a00120101` per charon but
  `0a03120101` per pluto (missing the empty-key field 1). No `charon_anchor.json`
  ladder entry covers map-entry presence, so this is not `ABSENT-OK` — it is a real
  interop risk: two clusters running pluto vs. charon nodes would compute different
  QBFT value hashes for an `UnsignedDataSet` containing an empty pubkey string or an
  empty per-DV data payload, breaking quorum. Not reported upstream to pluto yet.
  Byte-level diff confirmed isolated (no second divergence hiding underneath): for
  `empty_value`, pluto's bytes are exactly charon's map-entry content with the
  trailing `1200` (empty-value field, tag+len0) truncated, length byte adjusted to
  match — nothing else differs. For `empty_key`, pluto's bytes are exactly charon's
  map-entry content with the leading `0a00` (empty-key field, tag+len0) truncated —
  again nothing else differs. Reachability in a live cluster (code inspection only,
  not differential execution, so flagged as such): an empty *value* cannot arise from
  honest duty execution on either implementation — `unmarshalUnsignedData`
  (`core/unsigneddata.go`) requires bytes decodable as a real
  `AttestationData`/`VersionedProposal`/`AggregatedAttestation`/`SyncContribution`,
  none of which SSZ/JSON-marshal to zero bytes, and `marshalUnsignedData`'s output
  feeding `UnsignedDataSetToProto` (`core/proto.go`) is never empty
  for a real duty. An empty *key* similarly cannot arise from honest code — DV pubkeys
  are validated to a fixed length by `PubKey.Bytes()`/`PubKeyFromBytes`
  (`core/types.go`, `len(k) != pkLen` check) before ever reaching
  this map. Both edge cases are therefore reachable only via a malformed or malicious
  peer constructing a wire-level `UnsignedDataSet` protobuf directly (bypassing the
  normal duty-fetch/marshal path) — not something an honest node in a healthy cluster
  ever produces. This lowers the practical severity versus a "happens in normal
  operation" reading, but the divergence itself (pluto and charon hashing the same
  adversarial/malformed bytes differently) is still real and still a FAIL.

- **Pluto's v1.10 `Definition`/`Lock` structs are missing `#[serde(default)]` on
  multiple fields charon's Go marshaler may legitimately omit or null out (FAIL,
  task 4, `cluster_hashing/definition/all_empty_lists` and
  `cluster_hashing/lock/validator_without_deposit_data`).** One root cause —
  a missing serde default — recurring across at least three fields; **the true
  count of affected fields is not established**, because the first parse error
  in each case short-circuits `serde_json` before any later field is checked, so
  this list is a lower bound, not a total. Confirmed instances:
  (1) `cluster/definition.go`'s `Operators []Operator` and
  `ValidatorAddresses []ValidatorAddresses` fields have `json:"operators"` /
  `json:"validators"` with **no** `omitempty`, so Go's `encoding/json` marshals a
  nil slice as `"operators": null`. Pluto's `DefinitionV1x10.operators: Vec<OperatorV1X2OrLater>`
  and `.validator_addresses: Vec<ValidatorAddresses>`
  (`pluto/crates/cluster/src/definition.rs`) carry no `#[serde(default)]`, so
  `serde_json` rejects the key's `null` value with "invalid type: null, expected a
  sequence" instead of treating it as empty. (Pluto's own `deposit_amounts` field
  does handle `null` correctly, via a custom `DepositAmountsSerde` that explicitly
  wraps `DefaultOnNull` — the same treatment was not extended to `operators` or
  `validator_addresses`.) (2) `cluster/distvalidator.go`'s
  `PartialDepositData []DepositData` field is tagged
  `json:"partial_deposit_data,omitempty"`, so Go omits the key entirely when a
  validator has no partial deposits. Pluto's
  `DistValidatorV1x8orLater.partial_deposit_data: Vec<DepositData>`
  (`pluto/crates/cluster/src/distvalidator.rs`) also carries no
  `#[serde(default)]`, so `serde_json` rejects the file with "missing field
  `partial_deposit_data`" rather than defaulting to an empty vec. (3) **Masked
  behind (1)** in `all_empty_lists`: charon's `definitionJSONv1x10to11` struct
  (`cluster/definition.go`) tags `Timestamp` with `omitempty` (as it also does
  `Name`), so a definition with an empty timestamp legitimately omits the key.
  Pluto's `DefinitionV1x10.name: String` does carry `#[serde(default)]` and
  handles this correctly, but `DefinitionV1x10.timestamp: String`
  (`pluto/crates/cluster/src/definition.rs`) does not, so once (1) is
  hypothetically fixed the same case still fails with "missing field
  `timestamp`". Confirmed directly: mutating `all_empty_lists`'s `operators`/
  `validators` from `null` to `[]` (simulating a fix to (1)) still fails to
  parse on the missing `timestamp` key; adding an empty `timestamp` string on
  top of that mutation parses successfully, with no further blocker found in
  that specific probe (not a proof no more exist elsewhere in the struct). No
  `charon_anchor.json` ladder entry covers any of this — the ladder tracks
  *protocol behaviour* that postdates charon v1.7.1, and all of these field tags
  are unchanged, long-standing charon serialization behaviour, not a recent
  charon feature. Reachability: a definition with zero operators is degenerate
  (no real cluster has none), but a validator with zero partial deposits, or a
  definition with an empty timestamp, are realistic shapes — e.g. a validator
  whose deposit was already broadcast through another channel, an intermediate
  DKG artifact captured before partial deposit data is attached, or a definition
  built without a timestamp set. Either way, a real charon-produced JSON file in
  any of these shapes is rejected outright by pluto's loader, which is a genuine
  interop risk for any tool (this repo's own vector generator included) that
  hands pluto a charon artifact verbatim rather than a pluto-shaped round-trip.
  Pinned as two named known-divergence tests
  (`definition_known_divergence_null_operators_and_validators`,
  `lock_known_divergence_missing_partial_deposit_data`) rather than left
  permanently red, each asserting the current rejection and its error shape, so
  either flips loudly the moment pluto's parser changes — the `definition` test's
  doc comment now states explicitly that `all_empty_lists` has at least two
  independent parse blockers stacked, so a partial upstream fix (null handling
  alone) will not turn it green; the masked `timestamp` gap is not given its own
  pinned test, since it is unreachable while the first blocker stands and a test
  that cannot run is worse than a documented gap. Not reported upstream
  to pluto yet.

## Global Constraints

- Pluto is **never modified**. The harness lives in `consumers/rust/` and path-depends
  on a pluto checkout at `../../../pluto` relative to the package (i.e. `~/pluto` next
  to `~/distributed-validator-specs`). If the checkout is elsewhere, the user edits the
  paths in `Cargo.toml`; document this in the README, do not build indirection for it.
- Rust toolchain pinned to **1.95.0** (copy pluto's `rust-toolchain.toml`), edition 2024.
- Dependency versions that pluto also uses (`prost`, `serde_json`, `k256`, `tokio`,
  `hex`, `libp2p`) must be copied from pluto's `[workspace.dependencies]` so cargo
  unifies them — a second `prost` major version makes pluto's generated types unusable.
- The consumer's `Cargo.toml` must replicate pluto's
  `[patch.crates-io] multistream-select = { path = "../../../pluto/third_party/multistream-select" }`
  (required once `pluto-priority`/`pluto-p2p` are dependencies; harmless before).
- Vectors load from `../../test_vectors/` via `CARGO_MANIFEST_DIR`, overridable with
  `SPEC_VECTORS_DIR` (same env var as the Go consumer).
- Hex in suites is lowercase, unprefixed — except inside `cluster_hashing` case
  `input`s, which are verbatim charon files (`0x`-prefixed, Gwei as strings, `null`
  for empty lists).
- Every case runs as a named subcheck: iterate cases inside one `#[test]`/
  `#[tokio::test]`, collect failures into a `Vec<String>` naming
  `"{suite}/{group}/{case}"` and assert the vec is empty at the end — one bad case
  must not hide the rest.
- Code blocks below are normative for *what is asserted*. Exact pluto field names,
  types and paths were mapped from a read of pluto `67088a2` but not compiled; fix
  compile errors against the real crate without changing any assertion. If an
  assertion itself proves impossible (API truly unreachable), that is an
  `UNREACHABLE` verdict, not a rewrite.
- Never weaken an assertion to make a case green. Red → triage against the ladder →
  verdict → record.
- Commit after each task, on a feature branch (never directly to `main`).

---

### Task 1: Harness scaffold + `secp256k1_signatures`

The smallest suite against the most-public pluto API (`pluto-k1util`: everything
`pub`), so the scaffold is proven by a real check.

**Files:**
- Create: `consumers/rust/Cargo.toml`
- Create: `consumers/rust/rust-toolchain.toml`
- Create: `consumers/rust/.gitignore`
- Create: `consumers/rust/src/lib.rs`
- Create: `consumers/rust/tests/secp256k1_signatures.rs`
- Modify: `consumers/README.md` (Pluto row: link `rust/`, status "in progress")

**Interfaces:**
- Produces: `spec_vectors_pluto::load_suite(name: &str) -> serde_json::Value` and
  `spec_vectors_pluto::unhex(s: &str) -> Vec<u8>` — every later task consumes these.

- [ ] **Step 1: Write the package scaffold**

`consumers/rust/Cargo.toml` (copy the exact version requirements for `serde_json`,
`hex`, `k256` from `~/pluto/Cargo.toml` `[workspace.dependencies]`):

```toml
[package]
name = "spec-vectors-pluto"
version = "0.1.0"
edition = "2024"
publish = false
description = "Runs the spec's test_vectors/ suites against a pluto checkout at ../../../pluto"

[dependencies]
serde_json = "1"
hex = "0.4.3"

[dev-dependencies]
pluto-k1util = { path = "../../../pluto/crates/k1util" }
k256 = { version = "0.13", features = ["ecdsa"] }

[patch.crates-io]
multistream-select = { path = "../../../pluto/third_party/multistream-select" }
```

`consumers/rust/rust-toolchain.toml`:

```toml
[toolchain]
channel = "1.95.0"
components = ["rustfmt", "clippy"]
```

`consumers/rust/.gitignore`:

```
/target
Cargo.lock
```

`consumers/rust/src/lib.rs`:

```rust
//! Loader for the spec's test_vectors/ suites.
//!
//! Vectors are read from `../../test_vectors/` relative to this package, or from
//! `SPEC_VECTORS_DIR` when set. `load_suite` refuses a file whose `suite` field
//! does not match the requested name, so a stray copy cannot silently substitute.

use std::path::PathBuf;

pub fn vectors_dir() -> PathBuf {
    match std::env::var_os("SPEC_VECTORS_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../test_vectors"),
    }
}

pub fn load_suite(name: &str) -> serde_json::Value {
    let path = vectors_dir().join(format!("{name}.json"));
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let suite: serde_json::Value = serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("parse {}: {e}", path.display()));
    assert_eq!(suite["suite"], name, "suite field mismatch in {}", path.display());
    suite
}

pub fn unhex(s: &str) -> Vec<u8> {
    hex::decode(s).unwrap_or_else(|e| panic!("bad hex {s:?}: {e}"))
}
```

- [ ] **Step 2: Write the failing test**

`consumers/rust/tests/secp256k1_signatures.rs`. The suite carries one secret key and
cases of `{input.hash_hex, signature_hex, recovered_pubkey_hex}` — signing is RFC 6979
deterministic, so exact signature bytes are asserted, and recovery is asserted both
ways:

```rust
use spec_vectors_pluto::{load_suite, unhex};

#[test]
fn secp256k1_signatures() {
    let suite = load_suite("secp256k1_signatures");
    let secret = k256::SecretKey::from_slice(&unhex(suite["secret_hex"].as_str().unwrap()))
        .expect("suite secret key");
    let pubkey = secret.public_key();
    let mut failures = Vec::new();

    for case in suite["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let hash = unhex(case["input"]["hash_hex"].as_str().unwrap());
        let want_sig = unhex(case["signature_hex"].as_str().unwrap());
        let want_pub = unhex(case["recovered_pubkey_hex"].as_str().unwrap());

        match pluto_k1util::sign(&secret, &hash) {
            Ok(sig) if sig.to_vec() == want_sig => {}
            Ok(sig) => failures.push(format!(
                "{name}: sign gave {}, want {}", hex::encode(sig), hex::encode(&want_sig))),
            Err(e) => failures.push(format!("{name}: sign failed: {e}")),
        }
        match pluto_k1util::recover(&hash, &want_sig) {
            Ok(rec) if rec.to_sec1_bytes().to_vec() == want_pub => {}
            Ok(rec) => failures.push(format!(
                "{name}: recover gave {}, want {}",
                hex::encode(rec.to_sec1_bytes()), hex::encode(&want_pub))),
            Err(e) => failures.push(format!("{name}: recover failed: {e}")),
        }
        match pluto_k1util::verify_65(&pubkey, &hash, &want_sig) {
            Ok(true) => {}
            other => failures.push(format!("{name}: verify_65 gave {other:?}, want Ok(true)")),
        }
    }
    assert!(failures.is_empty(), "{} failures:\n{}", failures.len(), failures.join("\n"));
}
```

Check the vector's pubkey encoding first (`uv run python -c "import json;
print(json.load(open('test_vectors/secp256k1_signatures.json'))['pubkey_hex'])"`):
if it is 33 bytes it is SEC1 compressed and `to_sec1_bytes()` matches; if 65 bytes,
use `k256::EncodedPoint::from(&rec).to_untagged_bytes()` accordingly.

- [ ] **Step 3: Run it**

```bash
cd consumers/rust && cargo test --test secp256k1_signatures
```
Expected: compiles against `~/pluto` and all cases pass (charon and pluto share
RFC 6979 + low-S via k256). Any red case is a FAIL finding — triage per the taxonomy.

- [ ] **Step 4: Record the verdict**

Fill the pluto commit under test and row 1 of the Results table in this plan.

- [ ] **Step 5: Update `consumers/README.md` and commit**

Add to the consumer table: `| Pluto (Rust) | in progress — see plans/pluto-conformance.md | [rust/](rust) |`,
plus a short "Pluto consumer" section: sibling-checkout requirement, the
`cd consumers/rust && cargo test` invocation, and that pluto is never modified.

```bash
git checkout -b pluto-conformance
git add consumers/rust consumers/README.md plans/pluto-conformance.md
git commit -m "Add Rust consumer scaffold and secp256k1 suite for pluto"
```

---

### Task 2: `qbft_hashing` — deterministic encoding + SSZ hash roots

**Files:**
- Create: `consumers/rust/tests/qbft_hashing.rs`
- Modify: `consumers/rust/Cargo.toml` (add dev-deps)

**Interfaces:**
- Consumes: `load_suite`, `unhex` from Task 1.
- Pluto APIs: `pluto_consensus::qbft::msg::{hash_proto, hash_proto_bytes}` (both pub),
  prost-generated `Duty`, `UnsignedDataSet`, `QbftMsg` from `pluto-core`
  (`pluto_core::corepb::v1::…` — confirm the exact module path from
  `~/pluto/crates/core/src/lib.rs` before writing; the golden test at
  `~/pluto/crates/consensus/src/qbft/msg.rs:420` shows working imports to copy).

- [ ] **Step 1: Add dependencies**

```toml
pluto-consensus = { path = "../../../pluto/crates/consensus" }
pluto-core = { path = "../../../pluto/crates/core" }
prost = "<copy from pluto workspace>"
prost-types = "<copy from pluto workspace>"
```

- [ ] **Step 2: Write the test — four groups, one test fn each**

```rust
use prost::Message;
use spec_vectors_pluto::{load_suite, unhex};
// Adjust to pluto's real module path (see msg.rs golden test imports):
use pluto_core::corepb::v1::{Duty, QbftMsg, UnsignedDataSet};
use pluto_consensus::qbft::msg::{hash_proto, hash_proto_bytes};

fn check(failures: &mut Vec<String>, name: &str, encoded: &[u8], hash: [u8; 32],
         case: &serde_json::Value) {
    let want_enc = unhex(case["encoding_hex"].as_str().unwrap());
    let want_hash = unhex(case["hash_hex"].as_str().unwrap());
    if encoded != want_enc {
        failures.push(format!("{name}: encoding {}, want {}",
            hex::encode(encoded), hex::encode(&want_enc)));
    }
    if hash.as_slice() != want_hash {
        failures.push(format!("{name}: hash {}, want {}",
            hex::encode(hash), hex::encode(&want_hash)));
    }
}

#[test]
fn duty_hashing() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["duty"].as_array().unwrap() {
        let name = format!("duty/{}", case["name"].as_str().unwrap());
        let duty = Duty {
            slot: case["input"]["slot"].as_i64().unwrap(),
            r#type: case["input"]["type"].as_i64().unwrap() as i32,
        };
        // Covers the ≤32-byte rule: a short encoding is returned zero-padded, unhashed.
        match hash_proto(&duty) {
            Ok(h) => check(&mut failures, &name, &duty.encode_to_vec(), h, case),
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn unsigned_data_set_hashing() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["unsigned_data_set"].as_array().unwrap() {
        let name = format!("unsigned_data_set/{}", case["name"].as_str().unwrap());
        // Map keys/values are hex in the vector; pluto's set is BTreeMap<String, Bytes>.
        // Covers explicit map-entry presence: an empty value must still emit 0x1200.
        let set = case["input"]["set"].as_object().unwrap().iter()
            .map(|(k, v)| (k.clone(), unhex(v.as_str().unwrap()).into()))
            .collect();
        let uds = UnsignedDataSet { set };
        match hash_proto(&uds) {
            Ok(h) => check(&mut failures, &name, &uds.encode_to_vec(), h, case),
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn qbft_signing_roots() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["qbft_signing_root"].as_array().unwrap() {
        let name = format!("qbft_signing_root/{}", case["name"].as_str().unwrap());
        let i = &case["input"];
        // value_hash / prepared_value_hash are always 32 bytes on the wire,
        // zeros meaning "no value"; signature is empty when signing.
        let msg = QbftMsg {
            r#type: i["type"].as_i64().unwrap(),
            duty: Some(Duty {
                slot: i["slot"].as_i64().unwrap(),
                r#type: i["duty_type"].as_i64().unwrap() as i32,
            }),
            peer_idx: i["peer_idx"].as_i64().unwrap(),
            round: i["round"].as_i64().unwrap(),
            prepared_round: i["prepared_round"].as_i64().unwrap(),
            value_hash: unhex(i["value_hash"].as_str().unwrap()).into(),
            prepared_value_hash: unhex(i["prepared_value_hash"].as_str().unwrap()).into(),
            signature: Default::default(),
        };
        match hash_proto(&msg) {
            Ok(h) => check(&mut failures, &name, &msg.encode_to_vec(), h, case),
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn any_string_hashing() {
    // Charon's *priority* hashProto hashes the Any wrapper itself, type URL included.
    // Pluto's equivalent (calculate.rs hash_any) is private, but it is exactly
    // hash-of-the-Any-encoding, so hash_proto_bytes over the encoded Any exercises
    // pluto's real merkleization path on the same bytes.
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["any_string"].as_array().unwrap() {
        let name = format!("any_string/{}", case["name"].as_str().unwrap());
        let s = case["input"]["string_value"].as_str().unwrap();
        // google.protobuf.StringValue: field 1, length-delimited.
        let mut inner = Vec::new();
        prost::encoding::string::encode(1, &s.to_string(), &mut inner);
        let any = prost_types::Any {
            type_url: "type.googleapis.com/google.protobuf.StringValue".into(),
            value: inner,
        };
        let encoded = any.encode_to_vec();
        match hash_proto_bytes(&encoded) {
            Ok(h) => check(&mut failures, &name, &encoded, h, case),
            Err(e) => failures.push(format!("{name}: hash_proto_bytes failed: {e}")),
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
```

- [ ] **Step 3: Run it**

```bash
cargo test --test qbft_hashing
```
Expected: all four groups pass — pluto already consumes a charon-v1.7.1 hashproto
golden file and none of these values moved after v1.7.1. If the `any_string`
*encoding* diverges (type URL prefix differs), decode the vector's `encoding_hex`
to see charon's actual type URL and fix the constructed `type_url`, not the assertion.

- [ ] **Step 4: Record verdict in Results row 2; note in the row that pluto's own
  `crates/consensus/testdata/vectors/hashproto.json` is now redundant with this suite
  (the stated goal of the qbft_hashing suite) — a candidate upstream cleanup, not
  something this repo changes.**

- [ ] **Step 5: Commit**

```bash
git add consumers/rust plans/pluto-conformance.md
git commit -m "Run qbft_hashing suite against pluto"
```

---

### Task 3: `bls_threshold` — Lagrange aggregation and recovery

**Files:**
- Create: `consumers/rust/tests/bls_threshold.rs`
- Modify: `consumers/rust/Cargo.toml` (add `pluto-crypto = { path = "../../../pluto/crates/crypto" }`)

**Interfaces:**
- Consumes: `load_suite`, `unhex`.
- Pluto APIs: `pluto_crypto::blst_impl::BlstImpl` implementing `pluto_crypto::tbls::Tbls`
  (all trait methods pub); `pluto_crypto::types::{PublicKey, PrivateKey, Signature, Index}`
  are plain byte arrays. Share indices are 1-based, matching the suite.

- [ ] **Step 1: Write the test**

The suite pins: per-share pubkeys and partial signatures over `message_hex`, four
different quorums whose threshold aggregates must equal the group signature, secret
recovery, and a plain aggregate that must **not** verify under the group key.

```rust
use std::collections::HashMap;
use pluto_crypto::tbls::Tbls;
use pluto_crypto::blst_impl::BlstImpl;
use spec_vectors_pluto::{load_suite, unhex};

fn arr<const N: usize>(v: &[u8]) -> [u8; N] { v.try_into().expect("length") }

#[test]
fn bls_threshold() {
    let suite = load_suite("bls_threshold");
    let t = BlstImpl::default();
    let msg = unhex(suite["message_hex"].as_str().unwrap());
    let group_pub: [u8; 48] = arr(&unhex(suite["group_pubkey_hex"].as_str().unwrap()));
    let group_sig: [u8; 96] = arr(&unhex(suite["group_signature_hex"].as_str().unwrap()));
    let mut failures = Vec::new();

    // Index every share's secret, expected pubshare and expected partial signature.
    let mut secrets: HashMap<u64, [u8; 32]> = HashMap::new();
    let mut partials: HashMap<u64, [u8; 96]> = HashMap::new();
    for p in suite["partials"].as_array().unwrap() {
        let idx = p["input"]["share_idx"].as_u64().unwrap();
        let secret: [u8; 32] = arr(&unhex(p["input"]["secret_hex"].as_str().unwrap()));
        let want_pub: [u8; 48] = arr(&unhex(p["pubshare_hex"].as_str().unwrap()));
        let want_sig: [u8; 96] = arr(&unhex(p["signature_hex"].as_str().unwrap()));
        let name = p["name"].as_str().unwrap();

        match t.secret_to_public_key(&secret) {
            Ok(pk) if pk == want_pub => {}
            other => failures.push(format!("partials/{name}: pubshare {other:?}")),
        }
        match t.sign(&secret, &msg) {
            Ok(sig) if sig == want_sig => {}
            other => failures.push(format!("partials/{name}: partial sig {other:?}")),
        }
        secrets.insert(idx, secret);
        partials.insert(idx, want_sig);
    }

    // Four quorums: every threshold aggregate must equal the one group signature.
    for c in suite["threshold_aggregates"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let want: [u8; 96] = arr(&unhex(c["signature_hex"].as_str().unwrap()));
        let subset: HashMap<u64, [u8; 96]> = c["input"]["share_indices"].as_array().unwrap()
            .iter().map(|i| { let i = i.as_u64().unwrap(); (i, partials[&i]) }).collect();
        match t.threshold_aggregate(&subset) {
            Ok(sig) if sig == want => {}
            other => failures.push(format!("threshold_aggregates/{name}: {other:?}")),
        }
    }

    for c in suite["recovery"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let want_pub: [u8; 48] = arr(&unhex(c["pubkey_hex"].as_str().unwrap()));
        let subset: HashMap<u64, [u8; 32]> = c["input"]["share_indices"].as_array().unwrap()
            .iter().map(|i| { let i = i.as_u64().unwrap(); (i, secrets[&i]) }).collect();
        match t.recover_secret(&subset).and_then(|s| t.secret_to_public_key(&s)) {
            Ok(pk) if pk == want_pub => {}
            other => failures.push(format!("recovery/{name}: {other:?}")),
        }
    }

    // Plain aggregation is NOT threshold aggregation: exact bytes match the vector,
    // and the result must fail verification under the group key.
    for c in suite["plain_aggregate"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let want: [u8; 96] = arr(&unhex(c["signature_hex"].as_str().unwrap()));
        let sigs: Vec<[u8; 96]> = c["input"]["share_indices"].as_array().unwrap()
            .iter().map(|i| partials[&i.as_u64().unwrap()]).collect();
        match t.aggregate(&sigs) {
            Ok(sig) if sig == want => {
                if t.verify(&group_pub, &msg, &sig).is_ok() {
                    failures.push(format!(
                        "plain_aggregate/{name}: verified under group key, must not"));
                }
            }
            other => failures.push(format!("plain_aggregate/{name}: {other:?}")),
        }
    }

    if t.verify(&group_pub, &msg, &group_sig).is_err() {
        failures.push("group signature does not verify under group pubkey".into());
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
```

- [ ] **Step 2: Run** `cargo test --test bls_threshold`. Expected: PASS — pluto's
  `blst_impl` cites charon v1.7.1 parity and BLS did not change after it.

- [ ] **Step 3: Record verdict in Results row 3; commit**
  (`git commit -m "Run bls_threshold suite against pluto"`).

---

### Task 4: `cluster_hashing` — config/definition/lock hashes and full lock verification

**Files:**
- Create: `consumers/rust/tests/cluster_hashing.rs`
- Modify: `consumers/rust/Cargo.toml` (add `pluto-cluster = { path = "../../../pluto/crates/cluster" }`,
  `tokio = { version = "<pluto's>", features = ["macros", "rt"] }`)

**Interfaces:**
- Consumes: `load_suite` (case `input`s are verbatim charon cluster files — pass the
  raw JSON straight to pluto's serde).
- Pluto APIs: `pluto_cluster::definition::Definition` (serde + `set_definition_hashes`,
  `verify_hashes`), `pluto_cluster::lock::Lock` (`set_lock_hash`, `verify_hashes`,
  async `verify_signatures(&EthClient)`). Raw hash functions are `pub(crate)`; going
  through set-then-compare covers the same code.

- [ ] **Step 1: Write the test**

```rust
use spec_vectors_pluto::load_suite;
use pluto_cluster::{definition::Definition, lock::Lock};

#[test]
fn definition_hashes() {
    let suite = load_suite("cluster_hashing");
    let mut failures = Vec::new();
    for case in suite["definition"].as_array().unwrap() {
        let name = format!("definition/{}", case["name"].as_str().unwrap());
        let mut def: Definition = match serde_json::from_value(case["input"].clone()) {
            Ok(d) => d,
            Err(e) => { failures.push(format!("{name}: parse: {e}")); continue }
        };
        if let Err(e) = def.set_definition_hashes() {
            failures.push(format!("{name}: set_definition_hashes: {e}")); continue
        }
        let want_cfg = case["config_hash_hex"].as_str().unwrap();
        let want_def = case["definition_hash_hex"].as_str().unwrap();
        if hex::encode(&def.config_hash) != want_cfg {
            failures.push(format!("{name}: config_hash {}, want {want_cfg}",
                hex::encode(&def.config_hash)));
        }
        if hex::encode(&def.definition_hash) != want_def {
            failures.push(format!("{name}: definition_hash {}, want {want_def}",
                hex::encode(&def.definition_hash)));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[tokio::test]
async fn lock_hashes_and_verification() {
    let suite = load_suite("cluster_hashing");
    let mut failures = Vec::new();
    for case in suite["lock"].as_array().unwrap() {
        let name = format!("lock/{}", case["name"].as_str().unwrap());
        let mut lock: Lock = match serde_json::from_value(case["input"].clone()) {
            Ok(l) => l,
            Err(e) => { failures.push(format!("{name}: parse: {e}")); continue }
        };
        if let Err(e) = lock.set_lock_hash() {
            failures.push(format!("{name}: set_lock_hash: {e}")); continue
        }
        let want = case["lock_hash_hex"].as_str().unwrap();
        if hex::encode(&lock.lock_hash) != want {
            failures.push(format!("{name}: lock_hash {}, want {want}",
                hex::encode(&lock.lock_hash)));
        }
        if let Err(e) = lock.verify_hashes() {
            failures.push(format!("{name}: verify_hashes: {e}"));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
```

Before writing the field names for expected hashes, check the suite's actual keys
(`uv run python -c "import json; c=json.load(open('test_vectors/cluster_hashing.json'));
print(list(c['definition'][0]), list(c['lock'][0]))"`) — the plan's
`config_hash_hex`/`definition_hash_hex`/`lock_hash_hex` names must match what is there.

- [ ] **Step 2: Add the full-verification check for `real_keys_3_of_4`**

In the same file — this is the case that chains lock hash, public shares, plain BLS
aggregation and node signatures; only it carries real signatures:

```rust
#[tokio::test]
async fn real_keys_lock_verifies_end_to_end() {
    let suite = load_suite("cluster_hashing");
    let case = suite["lock"].as_array().unwrap().iter()
        .find(|c| c["name"] == "real_keys_3_of_4").expect("real_keys_3_of_4 present");
    let lock: Lock = serde_json::from_value(case["input"].clone()).expect("parse lock");
    lock.verify_hashes().expect("hashes");
    // EthClient::new("") is pluto's no-op EL client: skips only contract (EIP-1271)
    // signatures, still verifies EIP-712 operator sigs, the BLS aggregate over the
    // lock hash against all public shares, and every node signature against the
    // operator ENR keys. Confirm the exact constructor in crates/eth1wrap.
    let eth1 = pluto_eth1wrap::EthClient::new("");
    lock.verify_signatures(&eth1).await.expect("signature verification");
}
```

(Add `pluto-eth1wrap = { path = "../../../pluto/crates/eth1wrap" }` — confirm crate
name and constructor; if `verify_signatures` demands a live EL for these operators'
sig type, record that limitation in the Results row instead of mocking one.)

- [ ] **Step 3: Run** `cargo test --test cluster_hashing`. Expected: v1.10 files parse
  (pluto supports V1_0…V1_10) and all hashes match — pluto's own testdata includes
  charon's `cluster_lock_v1_10_0.json` golden. Parse *failures* here are findings:
  the inputs are verbatim charon files, so a rejection means pluto cannot load a real
  charon artifact.

- [ ] **Step 4: Record verdict in Results row 4; commit**
  (`git commit -m "Run cluster_hashing suite against pluto"`).

---

### Task 5: `priority_scoring` — cluster-wide priority results

The scoring function (`calculate_result`, `crates/priority/src/calculate.rs`) is
`pub(crate)`, so this goes end-to-end through `Prioritiser` with an in-process
libp2p network — pluto's own `crates/priority/tests/prioritiser_test.rs` is an
*external* test doing exactly this; copy its host-setup helpers.

**Files:**
- Create: `consumers/rust/tests/priority_scoring.rs`
- Modify: `consumers/rust/Cargo.toml` (add `pluto-priority`, `pluto-p2p`, `libp2p`,
  `async-trait` — versions from pluto's workspace; the `multistream-select` patch
  from Task 1 becomes load-bearing here)

**Interfaces:**
- Consumes: `load_suite`.
- Pluto APIs: `pluto_priority::{Prioritiser, component::sign_msg, PROTOCOL_ID}`, the
  `Consensus` trait (implement a mock capturing the proposed `PriorityResult`),
  `MsgVerifier` (`Box::new(|_| Ok(()))`), proto types `PriorityMsg`, `PriorityTopicProposal`.

- [ ] **Step 1: Write the harness**

Shape (helpers copied from `prioritiser_test.rs` — that file compiles against public
API only, so everything it does is available here):

```rust
// Per case:
//  1. Generate input.peers.len() secp256k1 keypairs; derive libp2p PeerIds; SORT the
//     PeerIds and assign them to the vector's peers ("0", "1", ...) in order — the
//     vector's expected ordering assumes ascending peer order, and scoring tie-breaks
//     are first-seen over peer_id-sorted input.
//  2. Start one in-process host per peer (swarm + Prioritiser::new_internal), with:
//       min_required = input.min_required,
//       msg_validator = Box::new(|_| Ok(())),
//       consensus = Arc<MockConsensus> capturing propose_priority's PriorityResult
//                   into a oneshot channel (leader only proposes once).
//  3. Build each peer's PriorityMsg: duty = Duty{slot: input.slot, type: PRIORITY},
//     topics = [Any-wrapped input.topic proposal with that peer's input priorities,
//               plus an Any-wrapped input.ignored_topic proposal] — mirror how
//     prioritiser_test.rs builds topic proposals; sign with
//     pluto_priority::component::sign_msg(&msg, &peer_secret).
//  4. Call prioritise() on every host concurrently; await the captured result with
//     a timeout (10s).
//  5. Compare: the result's entry for input.topic must list exactly the case's
//     `result` array in order — (priority, score) pairs if the vector carries
//     scores, else priorities_only().
```

Check the vector's `result` element shape first
(`uv run python -c "import json; d=json.load(open('test_vectors/priority_scoring.json'));
print([c['result'] for c in d['cases'] if c['result']][:2])"`) and assert score values
if present, order-only otherwise. Cases where `result` is `[]` assert the topic is
absent (below `min_required`) — an empty expected list is a *rejection* pin, not a
skip.

- [ ] **Step 2: Add the protocol-ID pin (ladder item 6)**

```rust
#[test]
fn priority_protocol_ids() {
    // Ladder: "Preferred priority protocol ID /charon/priority/2.0.0" is unreleased
    // (first_charon_release: null). At charon-v1.7.1 parity pluto must serve exactly
    // the legacy slash-less ID. When pluto adds the preferred ID, this test fails:
    // flip it to assert both IDs with the slash form preferred, per priority.md.
    assert_eq!(pluto_priority::PROTOCOL_ID, "charon/priority/2.0.0");
    assert_eq!(pluto_priority::protocols(), vec!["charon/priority/2.0.0"]);
}
```

- [ ] **Step 3: Run** `cargo test --test priority_scoring`. Expected: scoring cases
  PASS (the algorithm predates v1.7.1 and pluto's stable sort matches the spec).
  Watch the ties: charon v1.7.1 used an unstable sort — if any tie-case diverges,
  that is ladder entry "Stable sort of scored priorities" → triage before verdicting.

- [ ] **Step 4: Record verdict in Results row 5; commit**
  (`git commit -m "Run priority_scoring suite against pluto"`).

---

### Task 6: `timer_deadlines` — round timeouts under a paused clock

The vectors give `duty_start_delay_nanos`, `round_timeout_nanos` and absolute
`deadline_nanos` (= genesis + slot·duration + delay + timeout). Pluto's timers are
*relative* and the raw duration formulas are private, so this splits three ways:

- `round_timeout_nanos`: **testable** — await `RoundTimer::timer(round)` under
  `#[tokio::test(start_paused = true)]` and measure the deadline delta.
- `deadline_nanos` (genesis-derived determinism): ladder entry "Deterministic
  (genesis-derived) eager double linear round deadlines" (v1.9.0 > v1.7.1) → expected
  ABSENT-OK unless pluto's `with_duty` timers turn out to consume genesis (recent
  pluto commits touch the simnet duty cycle — check before assuming).
- `duty_start_delay_nanos`: `delay_slot_offset` is private in pluto's scheduler →
  expected UNREACHABLE; record `crates/core/src/scheduler.rs:853` in the row.

**Files:**
- Create: `consumers/rust/tests/timer_deadlines.rs`
- Modify: `consumers/rust/Cargo.toml` (`tokio` gains `["test-util", "time"]`,
  add `pluto-featureset = { path = "../../../pluto/crates/featureset" }` if
  `FeatureSet` lives there)

- [ ] **Step 1: Write the test**

```rust
use std::time::Duration;
use spec_vectors_pluto::load_suite;
use pluto_consensus::timer::{EagerDoubleLinearRoundTimer, RoundTimer};

#[tokio::test(start_paused = true)]
async fn round_timeouts() {
    let suite = load_suite("timer_deadlines");
    let mut failures = Vec::new();
    for case in suite["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let round = case["input"]["round"].as_i64().unwrap();
        let want = Duration::from_nanos(case["round_timeout_nanos"].as_u64().unwrap());

        // The default timer (no features) for every duty type at charon v1.7.1.
        // If the vectors select timers per duty type (proposer → linear), branch on
        // input.duty_type_name here, mirroring pluto's get_round_timer_func selection.
        let timer = EagerDoubleLinearRoundTimer::new();
        let start = tokio::time::Instant::now();
        let fut = timer.timer(round).expect("timer future");
        let deadline = fut.await; // paused clock: resolves at its Instant immediately
        let got = deadline - start;
        if got != want {
            failures.push(format!("{name}: round timeout {got:?}, want {want:?}"));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
```

Before running, read `~/pluto/crates/consensus/src/timer.rs` tests for how they await
the timer future under a paused clock and copy that pattern — if the future resolves
to its deadline `Instant` without needing `tokio::time::advance`, the above works; if
it sleeps, wrap with `tokio::time::timeout` + `advance`.

- [ ] **Step 2: Determine the two remaining columns' verdicts**

Read `EagerDoubleLinearRoundTimer::with_duty` and its callers: if no genesis/slot
timing enters the deadline, mark `deadline_nanos` ABSENT-OK (ladder v1.9.0 entry)
and add a pinned-divergence comment in the test naming the entry. Confirm
`delay_slot_offset` is still private → mark `duty_start_delay_nanos` UNREACHABLE
with file:line.

- [ ] **Step 3: Run** `cargo test --test timer_deadlines`. Triage: mismatches on
  linear rounds ≥ 2 are the known nanosecond bug (ladder "Linear round timer
  subsequent-round timeout fix", `null`) — if the vectors' proposer/linear cases hit
  it, split those cases into a pinned-divergence check asserting pluto's 200ns
  schedule, named for the ladder entry, and keep the rest strict.

- [ ] **Step 4: Record verdict in Results row 6 (verdict per column:
  timeout / deadline / start-delay); commit**
  (`git commit -m "Run timer_deadlines suite against pluto"`).

---

### Task 7: `qbft_msg_limits` — justification/value/wire-size rejection

**Files:**
- Create: `consumers/rust/tests/qbft_msg_limits.rs`

**Interfaces:**
- Pluto APIs: `pluto_consensus::qbft::{Consensus, Config, Peer}`,
  `pluto_consensus::qbft::p2p::MAX_CONSENSUS_MSG_SIZE`,
  `pluto_p2p::proto::{MAX_MESSAGE_SIZE, read_protobuf_with_max_size}`,
  `pluto_core::deadline::{DeadlinerHandle, AddOutcome}`, error variant
  `Error::TooManyJustifications`. Messages are signed by reproducing pluto's
  `sign_msg`: clear signature → `hash_proto` → `pluto_k1util::sign` (Task 2 proved
  the root; Task 1 proved the signature).

- [ ] **Step 1: Write the `counts` half**

```rust
// Per `counts` case (input: nodes, justification_count, value_count):
//  1. Build a `Consensus` for `nodes` peers: generate k256 keys, Peer{index, name,
//     public_key}; local_peer_idx 0; DeadlinerHandle::always(AddOutcome::Scheduled);
//     duty_gater = Arc::new(|_| true); broadcaster/sniffer = no-op closures;
//     timer_func = get_round_timer_func(FeatureSet::default()); a dummy expired_rx.
//     Copy the wiring from crates/consensus/examples/qbft.rs (external-crate-shaped).
//  2. Build a signed QbftConsensusMsg from peer 1 with `justification_count`
//     justification msgs (each itself signed) and `value_count` Any values.
//  3. `consensus.handle(msg, &ct).await`:
//       accepted == true  → expect Ok(())            (well-formed msg required)
//       reason "too_many_justifications" → expect Err(TooManyJustifications{..})
//       reason "too_many_values"         → see below
//
// Pre-registered divergences (ladder entry "QBFT DECIDED-resend rate limit and
// message size/count limits", first_charon_release: null — absent at v1.7.1):
//   - pluto's cap is 4n, not the spec's 2n: cases between 2n+1 and 4n will be
//     ACCEPTED. Pin that with an explicit ABSENT-OK branch asserting Ok(()) and
//     naming the ladder entry AND pluto's own constant (component.rs
//     MAX_JUSTIFICATIONS_PER_NODE = 4 — hardening pluto chose, neither charon
//     v1.7.1 nor spec; record as a Finding).
//   - `too_many_values` cases: no values cap exists — pin acceptance, ABSENT-OK.
// Cases the spec accepts must be accepted by pluto unconditionally: over-rejection
// breaks liveness and no ladder entry can excuse it.
```

- [ ] **Step 2: Write the `wire_size` half**

```rust
#[test]
fn wire_size_constants() {
    // The 32 MiB consensus limit is a spec-pinned narrowing of libp2p's 128 MiB
    // default; both constants are public in pluto.
    assert_eq!(pluto_consensus::qbft::p2p::MAX_CONSENSUS_MSG_SIZE, 32 * 1024 * 1024);
    assert_eq!(pluto_p2p::proto::MAX_MESSAGE_SIZE, 128 << 20);
}

#[tokio::test]
async fn wire_size_enforcement() {
    // Per wire_size case: feed a length-prefixed frame of input.wire_size_bytes
    // through read_protobuf_with_max_size(&mut stream, MAX_CONSENSUS_MSG_SIZE)
    // over an in-memory duplex (tokio::io::duplex). accepted → decodes (use a
    // padded valid message); rejected → Err. Mirror how qbft/p2p.rs invokes the
    // reader so the same code path is under test.
}
```

- [ ] **Step 3: Run** `cargo test --test qbft_msg_limits`, triage every red case
  against the pre-registered expectations — anything *outside* them (e.g. an
  at-limit case rejected) is a FAIL finding.

- [ ] **Step 4: Record verdict in Results row 7 and the 4n-cap finding under
  Findings; commit** (`git commit -m "Run qbft_msg_limits suite against pluto"`).

---

### Task 8: `qbft_decided_resends` — post-decision rebroadcast limiting

Pre-registered: pluto has **no limiter** (`crates/core/src/qbft/mod.rs:494-503`
rebroadcasts on every post-decision ROUND-CHANGE from another source). Ladder entry
`null` → expected ABSENT-OK. The check still runs the real state machine, because
"absent" asserted by inspection alone goes stale.

**Files:**
- Create: `consumers/rust/tests/qbft_decided_resends.rs`

**Interfaces:**
- Pluto APIs: `pluto_core::qbft::{run, Definition, Transport, QbftLogger, MessageType,
  MSG_ROUND_CHANGE, MSG_DECIDED, SomeMsg}` — all public with public fields; implement
  `QbftTypes` and `SomeMsg` for a minimal test message type.

- [ ] **Step 1: Write the harness**

```rust
// Per case (input: nodes, decided_round, events[{source, round}], rebroadcast[i]):
//  1. Implement TestTypes: QbftTypes with a trivial Value/Compare, and TestMsg:
//     SomeMsg returning the constructed type/round/source/value.
//  2. Definition { nodes, fifo_limit: 100, is_leader: |_,_,_| false (peer under test
//     never leads), new_timer: a never-firing timer, decide/compare/logger: no-ops }.
//  3. Transport.broadcast records every outgoing MSG_DECIDED into a Vec;
//     Transport.receive is a channel the test feeds.
//  4. Drive the instance to decision at input.decided_round: feed a justified
//     PRE-PREPARE for that round plus `quorum(nodes)` COMMITs — crib the exact
//     minimal message sequence from pluto's own core qbft tests
//     (crates/core/src/qbft/, internal but readable) or charon's TestDecidedRebroadcastLimits.
//  5. Feed each event as a ROUND-CHANGE from event.source at event.round; after each,
//     record whether a new DECIDED broadcast appeared.
//  6. Compare the per-event bool sequence with the vector's `rebroadcast` array under
//     BOTH readings:
//       spec reading  — expect mismatches once a source exceeds 16 or repeats a round
//       (limiter absent), i.e. the conformance columns FAIL;
//       pin reading   — pluto rebroadcasts on EVERY event from another source; assert
//       that exactly, named for the ladder entry, so the test flips when pluto adds
//       the limiter.
//     The test passes on the pin reading and prints the spec-reading mismatch count.
```

- [ ] **Step 2: Run** `cargo test --test qbft_decided_resends`.

Fallback, only if driving `run` externally proves impractical after a real attempt
(e.g. `SomeMsg` cannot be implemented outside the crate): verdict the row
UNREACHABLE, cite `crates/core/src/qbft/mod.rs:494-503` as the inspection evidence
for ABSENT-OK, and leave the test file in place with `#[ignore]` and a comment
explaining what blocked it.

- [ ] **Step 3: Record verdict in Results row 8; commit**
  (`git commit -m "Run qbft_decided_resends suite against pluto"`).

---

### Task 9: `parsigex_sender_binding` — share-index binding and peer-map validation

In charon this rule lives in the **DKG lock-hash exchanger** (`dkg/exchanger.go`).
First establish where pluto's equivalent is: grep `~/pluto/crates/dkg` and
`~/pluto/crates/parsigex` for `share_idx` validation and exchanger construction.
Pre-registered: no sender binding exists in the parsigex crate; ladder entry
"Sender-bound share indices in the DKG lock-hash exchange" (`null`) → ABSENT-OK
expected for the `cases` half. The `peer_map` half (complete-map validation,
positive share indices) predates v1.7.1 in charon, so it must PASS if the
construction is reachable.

**Files:**
- Create: `consumers/rust/tests/parsigex_sender_binding.rs`
- Modify: `consumers/rust/Cargo.toml` (add `pluto-parsigex`, and `pluto-dkg` if the
  exchanger lives there)

- [ ] **Step 1: Probe and write the test**

```rust
// cases (input: share_idx_by_peer {self, other}, sender, share_idx; accepted, reason):
//   If pluto has a sender-bound verifier (dkg exchanger or parsigex): drive it
//   directly per case. If not (pre-registered): pin the absence — build the closest
//   verifier pluto has, pluto_parsigex::new_eth2_verifier with a pub-shares map, show
//   a wrong-sender share_idx passes index lookup (the binding never fires), assert
//   that, name the ladder entry, verdict ABSENT-OK.
// peer_map (input: peers, share_idx_by_peer, peer_idx; accepted, reason):
//   Map to pluto's construction-time validation: whichever function builds the
//   peer→share-index map for the exchange (Definition::node_idx, dkg setup, or the
//   pub_shares_by_key map builder). Assert: complete map accepted; a participant
//   with no assigned index rejected (`unknown_peer`); non-positive share index
//   rejected (`missing_share_idx`). If the only builder is private
//   (crates/app/src/node/mod.rs:800), verdict that half UNREACHABLE with file:line.
```

- [ ] **Step 2: Run** `cargo test --test parsigex_sender_binding`, triage: a missing
  *peer-map* validation (accepting an incomplete map) is a FAIL finding — charon
  v1.7.1 already rejects it, no ladder cover. Sender-binding absence is ABSENT-OK.

- [ ] **Step 3: Record verdict in Results row 9; commit**
  (`git commit -m "Run parsigex_sender_binding suite against pluto"`).

---

### Task 10: Coverage guard, docs, and wrap-up

**Files:**
- Create: `consumers/rust/tests/coverage.rs`
- Modify: `consumers/README.md` (final Pluto row: suites run, pluto commit, verdicts)
- Modify: `tests/test_consumers.py` (extend to the Rust consumer)
- Modify: `plans/spec-completion.md` (Phase 3 item 2 pluto bullet → point here)

- [ ] **Step 1: Write the coverage guard**

The Go consumer's `TestEverySuiteIsCovered` has an equivalent here: an uncovered
suite is indistinguishable from a passing one.

```rust
use std::collections::BTreeSet;

/// Suite name -> test file that runs it. Update when a suite or test is added.
const COVERED: &[(&str, &str)] = &[
    ("secp256k1_signatures", "tests/secp256k1_signatures.rs"),
    ("qbft_hashing", "tests/qbft_hashing.rs"),
    ("bls_threshold", "tests/bls_threshold.rs"),
    ("cluster_hashing", "tests/cluster_hashing.rs"),
    ("priority_scoring", "tests/priority_scoring.rs"),
    ("timer_deadlines", "tests/timer_deadlines.rs"),
    ("qbft_msg_limits", "tests/qbft_msg_limits.rs"),
    ("qbft_decided_resends", "tests/qbft_decided_resends.rs"),
    ("parsigex_sender_binding", "tests/parsigex_sender_binding.rs"),
];

#[test]
fn every_suite_is_covered() {
    let published: BTreeSet<String> = std::fs::read_dir(spec_vectors_pluto::vectors_dir())
        .expect("vectors dir")
        .filter_map(|e| {
            let p = e.expect("dir entry").path();
            (p.extension()? == "json")
                .then(|| p.file_stem().unwrap().to_string_lossy().into_owned())
        })
        .collect();
    let covered: BTreeSet<String> = COVERED.iter().map(|(s, _)| s.to_string()).collect();
    assert_eq!(published, covered,
        "published suites and covered suites disagree — a suite nothing runs is a document, not a test");
    for (suite, file) in COVERED {
        assert!(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(file).exists(),
            "{suite}: declared test file {file} does not exist");
    }
}
```

- [ ] **Step 2: Extend `tests/test_consumers.py`**

Mirror the existing Go mapping check: assert each of the nine suites appears in
`consumers/rust/tests/coverage.rs`'s `COVERED` table and that each declared test
file exists — read the file with a regex over the `("suite", "file")` pairs, the
same technique the file already uses for the Go side (the Rust code is not compiled
here either). Run `uv run pytest tests/test_consumers.py` and confirm green.

- [ ] **Step 3: Finalize docs**

- `consumers/README.md`: Pluto row lists suites run / subcheck count / pluto commit /
  verdict summary, and a "running it" snippet:
  ```bash
  # pluto checked out as a sibling of this repo (default: ../pluto)
  cd consumers/rust && cargo test
  ```
- `plans/spec-completion.md` Phase 3 item 2: change the pluto bullet from
  "not started" to a pointer at this plan and its Results table.

- [ ] **Step 4: Full run + quality checks**

```bash
cd consumers/rust && cargo fmt --check && cargo clippy --all-targets && cargo test
cd ../.. && uv run tox -e all-checks && uv run pytest tests/test_consumers.py
```

- [ ] **Step 5: Record Results row 10, finalize the Findings section (each finding:
  divergence, pluto file:line, ladder cover or not, reported upstream or not),
  commit, and open the PR**

```bash
git add -A && git commit -m "Add coverage guard and docs for the pluto consumer"
gh pr create --title "Rust consumer: run spec vectors against pluto" \
  --body "..."   # summarize verdicts per suite; plain factual language
```
