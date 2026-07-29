# Spec Completion Plan

Status as of 2026-07-28. Goal: make this repo a formal spec of the Obol DV
protocol (as implemented by charon) precise enough that pluto is assured of
perfect interop with charon.

Context anchors:
- Spec validated against charon main @ `2eb6798e` (2026-07-14, during v1.11.0 RCs).
- Pluto pins parity to charon **v1.7.1**, will come forward to charon main
  (and future versions) once complete to 1.7.1. Pluto does not consume this
  spec yet — its parity target is charon Go source (see pluto AGENTS.md).
- Known normative quirk: priority protocol ID is `charon/priority/2.0.0`
  (no leading slash) — accidental in charon, accommodated by pluto, now
  documented in this spec. Do not "fix" unless charon versions the protocol.
  (An unmerged charon branch `pinebit/fix-priority-slash` adds the slash with a
  legacy alias; the spec stays on the no-slash form until that lands on main.)

## Phase 1 — Un-stale (DONE, this PR)

- [x] `MsgSync.nickname` field 6 (charon #4105, in v1.9.0 — commit `d33572f2`
      is an ancestor of the v1.9.0 tag)
- [x] Deterministic genesis/slot-derived deadlines + duty start delay in
      `DoubleEagerLinearRoundTimer` (charon #4243, in v1.9.0 — commit
      `31ff2996` is an ancestor of the v1.9.0 tag)
- [x] QBFT hardening (charon #4557, in v1.11.0): DECIDED-resend rate limit
      (16/source, strictly-increasing round), `MAX_CONSENSUS_MSG_SIZE` (32 MiB),
      `verify_msg_limits` (justifications ≤ 2n, values ≤ 2(j+1))
- [x] Rename `subspecs/bcast` → `subspecs/reliable_bcast` (disambiguate from
      charon `core/bcast`); wire protocol ID unchanged
- [x] Priority protocol ID leading-slash fix + warning
- [x] Charon version anchor section in README (incl. v1.7.1 compat table)
- [x] Pluto mentions (README Implementations table, docs/index.md)
- [ ] Deliberately skipped: cluster definition doc stays at v1.10 (per Oisín,
      v1.10 is the target for now; charon is on v1.11 — revisit later)

## Phase 2 — Close interop-critical gaps (DONE except item 7)

Priority order:

1. [x] **FROST DKG** (top priority — pluto's near-term DKG target, and charon's
   default scheme; the spec previously only covered opt-in Pedersen):
   - [x] Protocol IDs. Correction to the original plan note: charon builds these
     with `path.Join("/charon/dkg/frost/2.0.0/", suffix)`, which **normalises
     away the trailing slash**. The wire values are
     `/charon/dkg/frost/2.0.0/{round1/cast,round1/p2p,round2/cast}`, verified by
     running `path.Join`. Also note the two `cast` IDs are *bcast message IDs*,
     not libp2p protocol IDs — only `round1/p2p` has a stream handler.
   - [x] Executable message models mirroring `dkg/dkgpb/v1/frost.proto`
     (`subspecs/dkg/frost.py`, `proto/frost.proto`), plus receiver-side
     validation rules, round completion counts, and output assembly
   - [x] Flow spec from charon `dkg/frost.go` + `dkg/frostp2p.go`
     (`runFrostParallel`), incl. the DKG context string `"0x" + hex(defhash)`
   - [x] Node signature exchange `/charon/dkg/node_sig` (`subspecs/dkg/node_sigs.py`,
     `proto/nodesigs.proto`) — unversioned ID, `0xdeadbeef` sentinel
   - [x] Doc page `docs/dv-spec/dkg-frost.md`; Pedersen marked as the
     non-default alternative in README/docs
   - [x] Renamed `subspecs/dkg/message.py` → `pedersen.py` and extracted the
     shared output artifact to `subspecs/dkg/share.py` (mirrors charon
     `dkg/share`), since both algorithms produce it
2. [x] **sigagg**: `subspecs/sigagg/` + `docs/dv-spec/sigagg.md` — partial sig
   verification rules, the exact parsigdb threshold trigger (group by message
   root, `== threshold` so it fires exactly once), Lagrange aggregate
   construction over 1-based share indices, and the distinction between
   threshold aggregation (duties, deposit data, registrations) and plain
   aggregation (lock hash multi-signature)
3. [x] **infosync**: `subspecs/infosync/` + `docs/dv-spec/infosync.md` — the
   three topics, last-slot-of-epoch trigger, local ordering rules (lock
   preference then CLI config), slot-keyed result lookup, and consensus
   protocol selection by `/charon/consensus/` prefix
4. [x] **DKG reshare / add / remove / replace operator flows**:
   `subspecs/dkg/protocols.py` + `docs/dv-spec/dkg-cluster-edits.md` — the
   shared 4-step framework, the departing-operator variant, participant sets,
   threshold override bounds, and the ceremony-gapped vs new-lock-compacted
   share index distinction. Concrete step numbering for both ceremony types
   added to `docs/dv-spec/dkg-sync.md`
5. [x] **validatorapi conformance**: full endpoint-by-endpoint delta table in
   `docs/dv-spec/validatorapi.md`, generated from `core/validatorapi/router.go`
6. [x] Prose specs: scheduler slot offsets and their link to the consensus round
   timer (`docs/dv-spec/duty-scheduling.md`), and beacon broadcast
   (`docs/dv-spec/broadcast.md`). Note: `core/bcast` **recast** no longer exists
   in charon — builder registrations are now submitted by the scheduler, which
   is what the duty-scheduling doc now describes.
7. [ ] Cluster definition v1.11 — still deferred; v1.10 remains the target per
   Oisín (see Phase 1 note).

### Corrections made to existing specs while doing the above

Found by cross-checking against charon; all were wrong before this pass:

- `ParSignedData.share_idx` was documented and constrained as 0-based. It is
  **1-based** (`PeerIdx + 1`) and is the Lagrange evaluation point, so this was
  interop-fatal. Model constraint, description and tests updated.
- `DutyType.BUILDER_REGISTRATION` was marked deprecated. Only
  `BUILDER_PROPOSER` is (by v3 block proposals).
- validatorapi doc listed `POST /eth/v1/beacon/blocks` and
  `/eth/v1/beacon/blinded_blocks` as 404 — both are handled. It also omitted
  the endpoints that *are* 404 (`/eth/v1/beacon/pool/attestations`,
  `/eth/v2/validator/blocks/{slot}`), and listed
  `/eth/v1/beacon/states/{state_id}/validators` as proxied when it is
  intercepted for pubkey translation.
- duty-scheduling doc said builder registrations are submitted via
  `prepare_beacon_proposer`; they go to `register_validator`, at slot 0 of each
  epoch, delayed to 3/4 into the slot, at most once per epoch.
- `mkdocs.yml` nav pointed at a non-existent `specs/pedersen-dkg.md` and omitted
  every real spec page; now a complete grouped nav.
- `tox.ini` default `env_list` ran `mkdocs serve`, so the documented
  "run everything" command (`uv run tox`) could never terminate. Now uses
  `docs-build`.
- Line-anchored source links (`message.py#L86-L103`) replaced with plain file
  links in the pages that had them, since they silently rot.

## Doc source links (DONE, follow-up pass)

All 48 `../../src/...` and `../../proto/...` links resolved when browsing the
repo but warned on `mkdocs build` and 404'd on the published site. Now absolute
`https://github.com/ObolNetwork/distributed-validator-specs/blob/main/...`
URLs, which work in both contexts. Since mkdocs cannot validate absolute URLs,
the guardrails are:

- `tests/test_docs_links.py` — every linked path must exist in the repo; no page
  may reintroduce a `../../` escape or a `#L` line anchor.
- `tox.ini` `docs-build` now runs `mkdocs build --strict`, so a relative escape
  fails CI rather than printing a warning nobody reads.

Also fixed in this pass:

- `consensus.md` and `peerinfo.md` still carried the line anchors the note above
  claims were removed; they are gone now.
- Broken in-page anchors: `networking.md` `#Encodings` → `#encodings`;
  `consensus.md` `#duty-types` pointed at a heading that does not exist on the
  page and now links `DutyType` in `types/duty.py`.
- `networking.md` linked `../../ssz/simple-serialize.md`, which resolves only
  inside `ethereum/consensus-specs` (the page's origin). Now points upstream.
- The QBFT validation-rule list repeated one identical link on eight bullets.
  The module is linked once above the list and the bullets name the symbol.

## Phase 3 — Conformance testing

1. **Spec-generated test vectors** (`test_vectors/`, JSON) — DONE, 6 suites.

   Decisions (2026-07-28, Andrei): one JSON file per suite; vectors checked in as
   fixtures rather than generated at release time.

   Delivered:
   - [x] **Canonical encoding and hashing implemented, not just described.** The
     spec previously had a placeholder `SSZHasher` using Python's `hash()` —
     process-randomised, so the spec's "deterministic hash root" was neither.
     Now `src/dv_spec/encoding/{proto,ssz}.py`: deterministic proto3 encoding
     and `hash_proto` (SSZ merkleization of the encoding). Doc page
     `docs/dv-spec/hashing.md`. No new dependency: the encoder is explicit
     rather than protoc-generated, which is what makes the three determinism
     rules (field order, map key order, zero-value omission vs explicit
     presence) auditable by a reader of the spec.
   - [x] **QBFT signing root** (`subspecs/consensus/qbft/hashing.py`).
     `transport._sign_message` was hashing `msg.model_dump()` — a Python dict —
     and now uses the real signing root.
   - [x] `test_vectors/qbft_hashing.json` — 25 cases, **all values produced by
     charon** via `test_vectors/charon/hashproto_generator/main.go` (kept in-tree so
     the goldens can be re-derived). Covers duties, `UnsignedDataSet`, QBFT
     signing roots and `Any`-wrapped strings, including the edge cases that
     break naive encoders. Five cases are the real beacon duty payloads from
     pluto's `crates/consensus/testdata/vectors/hashproto.json` (charon v1.7.1),
     so pluto can drop that file and depend on this suite instead — which was
     the stated point of this item.
   - [x] `test_vectors/priority_scoring.json` — 18 cases transcribed from
     charon's own `TestCalculateResults` table, plus a new spec implementation
     (`subspecs/priority/scoring.py`) that reproduces every expected score.
     Priority previously had models but no scoring algorithm.
   - [x] `test_vectors/timer_deadlines.json` — 216 cases in integer nanoseconds.
   - [x] `tests/test_vectors.py` runs every suite; `scripts/generate_test_vectors.py`
     regenerates the spec-computed suites; `test_vectors/README.md` documents the
     format, provenance and how to reproduce the charon goldens.

   Crypto dependency decision (2026-07-28, Andrei): `py_ecc` accepted — pure
   Python is fine, the spec has no performance requirement. `eth-keys` with its
   native (pure Python) backend covers secp256k1 and shares `py_ecc`'s
   `eth-utils`/`eth-typing` base, so the two together added 9 packages and no
   C build step.

   Delivered on the back of that:
   - [x] `src/dv_spec/crypto/{bls,secp256k1}.py`. BLS is the Ethereum scheme
     `BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_POP_`, which is what charon reaches
     via Herumi `SetETHmode(EthModeLatest)`; py_ecc's `G2ProofOfPossession`
     reproduces charon byte-for-byte.
   - [x] `sigagg/aggregation.py` no longer declares BLS arithmetic out of scope:
     `threshold_aggregate` (Lagrange in G2) and `recover_pubkey` (the same in G1)
     are implemented, and `lagrange_coefficient` moved to `crypto/bls.py` so the
     curve order has one definition.
   - [x] The `Secp256k1Signer` placeholder that returned 65 zero bytes is gone.
     `transport._sign_message` now produces real signatures.
   - [x] `test_vectors/bls_threshold.json` — a fixed 3-of-4 sharing, charon's
     public shares, partial signatures, and **four different quorums** whose
     threshold aggregates must all equal the group signature. One quorum proves
     nothing: wrong coefficients still yield a well-formed signature. Also pins
     plain aggregation *not* verifying under the group key.
   - [x] `test_vectors/secp256k1_signatures.json` — exact signature bytes, which
     is possible because the RFC 6979 nonce makes signing deterministic. One
     case signs the QBFT signing root from `qbft_hashing.json`, so the suites
     chain.

   FROST transcript decision (2026-07-29, Andrei): **closed, not deferred.** A
   ceremony's round 1 commitments depend on each node's random polynomial, so a
   wire transcript is not reproducible without a seeded-RNG hook in charon. We
   will not change charon to suit the spec. The vectors therefore cover what
   actually has to match — the ceremony's *outputs* and their aggregation, in
   `bls_threshold.json`. Do not reopen this as a vector suite; a divergence in
   FROST's wire format has to be caught by the wire-level harness (item 4) or by
   differential fuzzing, not by a golden transcript.

   Cluster lock hash (DONE, 2026-07-29) — the sixth suite, and the one that
   needed a data model rather than just vectors:
   - [x] `src/dv_spec/cluster/`: Pydantic models for Definition, Operator,
     Creator, ValidatorAddresses, Lock, DistValidator, DepositData,
     BuilderRegistration and Registration at v1.10.0. They parse charon's own
     cluster files verbatim, which is a conformance property in its own right —
     pluto has to read the same files. Two Go-JSON quirks had to be reproduced:
     `0x`-prefixed hex for byte fields (optional on read), and `null` rather than
     `[]` for every empty list, because Go marshals a nil slice that way.
   - [x] `encoding/ssz.py` gained `HashWalker`, mirroring the fastssz interface
     charon hashes through, plus limit-aware merkleization, `calculate_limit`,
     `put_byte_list` and `put_bytes_n`. The walker approach is what makes
     version-dependent field sets expressible: the config hash and the definition
     hash are the same walk with `config_only` flipped.
   - [x] `cluster/hashing.py`: `config_hash`, `definition_hash`, `lock_hash` and
     `verify_definition_hashes`/`verify_lock_hash`, from `hashDefinitionV1x10`,
     `hashLockV1x3orLater`, `hashValidatorV1x8OrLater`,
     `hashDepositDataV1x7OrLater`, `hashBuilderRegistration` and
     `hashRegistration`. v1.10 only, per the Phase 1 decision; the module
     documents what v1.9 and v1.11 change.
   - [x] `cluster/verification.py`: the lock's plain BLS aggregate, the per-operator
     secp256k1 node signatures, the pubshare count/uniqueness rules, and charon's
     share-reconstruction check — which verifies *every* share individually, not
     just the first quorum.
   - [x] `test_vectors/cluster_hashing.json` — 6 definition and 4 lock cases, all
     hashes from charon via `test_vectors/charon/cluster_generator/main.go`. Two
     cases carry the most weight: `unsigned_single_operator`/`signed_single_operator`
     are the same definition before and after signing, pinning that the config hash
     does **not** move (an implementation that gets this wrong invalidates every
     signature already collected); and `real_keys_3_of_4` is a lock with the same
     3-of-4 sharing as `bls_threshold.json`, a real signature aggregate and real
     node signatures whose keys really are in the operators' ENRs, so the whole
     verification sequence runs against it. The generator refuses to emit that case
     unless charon itself accepts both signature sets.
   - [x] `docs/dv-spec/cluster-files.md` gained an SSZ hashing rules section (the
     field tables could not express left-pad vs right-pad, tree sizing by capacity,
     the mixin formula, or the `ByteList[N]` chunk rounding), a "verifying a lock
     before use" sequence, and the vector pointers. `hashing.md` no longer claims
     every DV hash is over protobuf bytes.

   Still outstanding:
   - Publishing as versioned release artifacts, which depends on the versioning
     policy under Aspirations.

2. **Consumer suites**: Go test package in charon + Rust test crate in pluto
   loading vectors from a pinned spec release. Catches charon regressions
   against its own documented protocol, not just pluto divergence.
3. **Spec-conformance CI here**: checkout charon@pinned + pluto@pinned, run
   both vector suites; scheduled weekly run against charon@main as the
   staleness alarm.
4. **Wire-level harness**: extend pluto's mixed docker-compose/dkg-runner
   infra; spec Python as passive protocol oracle (decode captured protobuf,
   validate QBFT transcripts against `protocol.py`).

### Findings from doing the above

Cross-checked against charon; each was verified by running charon's own code, not
by reading it:

- `QBFTMsg.value_hash`/`prepared_value_hash` are **always 32 bytes on the wire**,
  zeros meaning "no value" — charon's `createMsg` passes `[32]byte` slices. A
  sender that omitted an empty hash field would produce a signing root no
  receiver can reproduce. `encode_qbft_msg` now emits both unconditionally.
- **Map entry key/value fields have explicit presence**, unlike ordinary proto3
  singular fields: an `UnsignedDataSet` entry with an empty value emits `0x1200`.
- **An encoding of ≤32 bytes is not hashed at all** — `hash_proto` returns it
  zero-padded. `Duty{slot: 1, type: 2}` "hashes" to `0x0801100200…00`.
- Charon's priority result ordering documents a tie-break by lowest peer ID, but
  implements it with Go's `slices.SortFunc`, which is **not stable**. It holds
  only because Go's pdqsort falls back to insertion sort below 13 elements. The
  spec sorts stably and documents the divergence risk.
- The duty start delay is **integer division at nanosecond resolution**
  (`time.Duration`), so a 5s slot (Gnosis Chain) gives an attester delay of
  1666666666ns. The spec's float helper was silently 0.33ns off; there is now an
  integer-nanosecond API and the vectors are normative in integers.

From the cluster hashing pass:

- **Cluster files carry `null`, not `[]`, for every empty list**, because Go
  marshals a nil slice that way. A reader that rejects null cannot load a charon
  file with, say, no partial deposit data. Both parse to the same hash, since a
  list mixes in a length of zero either way.
- **A short fixed-size field is left-padded**, so an absent 65-byte signature
  hashes exactly as an all-zero one. Combined with the config hash excluding
  signatures, that means an unsigned definition, a zero-signature definition and a
  fully signed one all share a config hash.
- **`BuilderRegistration.Message.FeeRecipient` is the one exception**: charon writes
  it with `PutBytes` rather than a fixed length, so a short value is right-padded.
  An implementation that treated it as `Bytes20` like every other address would
  agree on all realistic inputs and diverge on a short one.
- **List trees are sized to the declared capacity, not the contents.**
  `deposit_amounts` is `uint64[256]`, which is 64 chunks, so it is a depth-6 tree
  holding one element. Sizing to the contents gives a different root for every
  list in the file.
- **`ByteList[N]` rounds its capacity up to whole chunks**, so `ByteList[16]` and
  `ByteList[32]` produce single-leaf trees; the mixed-in length is the data's byte
  count, so the same bytes hash identically under either capacity — `version` and
  `timestamp` share a tree shape.
- Charon's fastssz `Merkleize` does not align the buffer before merkleizing, and
  truncates a trailing partial chunk if one exists. No cluster field leaves the
  buffer unaligned, so this never fires; the spec raises rather than reproducing
  the truncation, so a future field that did would fail loudly instead of hashing
  differently.

From the adversarial review of that pass (2026-07-29, differential execution
against charon — 57 hand-built edge cases, 400 randomized definitions, three
`NewForT` locks; all hashes agree):

- **Charon hashes negative integers by two's-complement wrap.** Its numeric
  fields are signed Go ints cast with `uint64(v)` in `cluster/ssz.go`, so
  `"threshold": -1` in a lock file parses and hashes in charon. The spec bounds
  these fields (`ge=0`; `le=2^63-1`, Go's own parse limit) and rejects the file
  at validation instead of reproducing the wrap.
- **`phase0.Gwei` unmarshals only from a quoted string**, so deposit amounts
  must be *written* as JSON strings too — a bare number is unreadable by charon.
  The models now serialize them as strings.
- **Charon's `verifyNodeSignatures` checks against the stored `lock_hash` field**,
  not a recomputation — safe only because `LoadClusterLock` verifies hashes
  first, and under `--no-verify` a mismatch is only logged. The spec recomputes
  the hash, which assumes nothing about call order.
- **Go's `hex.DecodeString` rejects whitespace; Python's `bytes.fromhex` skips
  it.** The spec's hex decoding now rejects whitespace so it cannot accept a
  file charon rejects.
- **Charon rejects a duplicated public share within a validator**
  (`parsePubShares`), and reconstruction alone cannot be relied on to catch it —
  a polynomial can legitimately take the same value at two points. The spec
  checks this in `verify_pubshare_counts`.
- **Charon rejects a definition whose `num_validators` disagrees with its
  `validators` list length** at load. The spec enforces the same at parse.

## Aspirations (agreed, later)

- **Adversarial/negative vectors**: oversized justification → reject,
  decided-resend flood → rate-limit; doubles as security regression tests.
- **Differential fuzzing**: random QBFT message sequences into spec-Python,
  charon-Go, pluto-Rust state machines; compare outputs.
- **Pluto link-back**: one-line PR to pluto README/AGENTS.md referencing this
  spec once Phase 1 lands ("read the spec; Go source is the reference impl").
- **Versioning policy**: tagged spec releases (`spec-v1.7.1`, `spec-v1.8.x`)
  mapped to charon MAJOR.MINOR so pluto's version-forward path has an
  artifact trail.
- **Proto parity CI**: buf breaking-change diff of `proto/` against charon's
  `core/corepb`/`dkg/dkgpb` at the pinned commit (would have caught the
  missing `nickname` field automatically).
- Quirks registry doc: deferred until we accumulate more than the priority
  slash + dkg-sync trailing slash.

## Explicitly out of scope for the spec

Internal, non-wire-visible charon components: dutydb, aggsigdb, deadliner,
tracker (observability), parsigcache. Specify behaviorally only where
observable (e.g. the threshold that triggers aggregation).
