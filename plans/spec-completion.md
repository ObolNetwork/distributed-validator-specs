# Spec Completion Plan

Status as of 2026-07-30. Goal: make this repo a formal spec of the Obol DV
protocol (as implemented by charon) precise enough that pluto is assured of
perfect interop with charon.

Context anchors:
- Spec validated against charon main @ `6054bcb2` (2026-07-29, during v1.11.0 RCs).
- Pluto pins parity to charon **v1.7.1**, will come forward to charon main
  (and future versions) once complete to 1.7.1. Pluto does not consume this
  spec yet — its parity target is charon Go source (see pluto AGENTS.md).
- Priority now has **two** protocol IDs: `/charon/priority/2.0.0` preferred and
  `charon/priority/2.0.0` (no leading slash) as a legacy alias. Both must be
  served — the legacy form is the only one any released charon speaks. See
  Phase 1.1.

## Phase 1 — Un-stale (DONE, this PR)

- [x] `MsgSync.nickname` field 6 (charon #4105, in v1.9.0 — commit `d33572f2`
      is an ancestor of the v1.9.0 tag)
- [x] Deterministic genesis/slot-derived deadlines + duty start delay in
      `DoubleEagerLinearRoundTimer` (charon #4243, in v1.9.0 — commit
      `31ff2996` is an ancestor of the v1.9.0 tag)
- [x] QBFT hardening (charon #4557, in the v1.11.0 RCs): DECIDED-resend rate limit
      (16/source, strictly-increasing round), `MAX_CONSENSUS_MSG_SIZE` (32 MiB),
      `verify_msg_limits` (justifications ≤ 2n, values ≤ 2(j+1))
- [x] Rename `subspecs/bcast` → `subspecs/reliable_bcast` (disambiguate from
      charon `core/bcast`); wire protocol ID unchanged
- [x] Priority protocol ID leading-slash fix + warning
- [x] Charon version anchor section in README (incl. v1.7.1 compat table)
- [x] Pluto mentions (README Implementations table, docs/index.md)
- [ ] Deliberately skipped: cluster definition doc stays at v1.10 (per Oisín,
      v1.10 is the target for now; charon is on v1.11 — revisit later)

## Phase 1.1 — Re-anchor to charon main (DONE, 2026-07-30)

Charon moved eight commits past the `2eb6798e` anchor before anyone noticed, so
this is the drift Phase 3.3 exists to catch automatically. Found by reading a
local charon checkout, not by any alarm. Three commits touched spec surface, all
unreleased (charon's latest tag is `v1.11.0-rc1`, which contains none of them):

- [x] **Priority protocol ID** (charon #4605, `3335e6eb`) — the leading-slash fix
      this plan said it was waiting on has landed. `/charon/priority/2.0.0` is now
      preferred, `charon/priority/2.0.0` is a legacy alias, and **both must be
      served**: a dialler offers both with the slash form first, a listener
      registers each separately as an exact match. Registering them together
      under a common prefix collapses that prefix to bare `*`, which libp2p
      identify then advertises in place of either real ID — specified in
      `priority.md` because it is an interop trap, not an implementation detail.
      Charon targets `v1.12` for the preferred ID and `v1.14` for alias removal.
- [x] **Stable priority sort** (charon #4611, `6054bcb2`) — charon now uses
      `slices.SortStableFunc`, so the divergence risk this plan recorded is gone.
      The spec was already correct; the warning became a statement.
- [x] **ParSigEx sender binding** (charon #4599, `7bcc511e`) — the handler passes
      the authenticated libp2p sender to the verifier. The DKG lock-hash exchange
      enforces that a peer may only contribute under its own assigned share index
      (`verify_peer_share_idx`); the core workflow deliberately does not, since
      those signatures are already verified against the pubshare for the claimed
      index. Expected indices resolve through a **peer map**, not peer position,
      because removal leaves survivors with gapped indices — the case that breaks
      a position-derived implementation. Construction rejects a participant with
      no assigned index (`validate_exchange_peers`), because otherwise its
      signatures are dropped as unknown and the exchange silently times out.

Assessed and ruled **out of scope**: charon #4610 (`7c0354f1`) raises the
deadliner window for `DutySyncMessage`/`DutySyncContribution` to a full slot.
That is `core/deadline.go`, and the deadliner is on the out-of-scope list below.
The remaining four commits are dependency bumps and a flaky-test fix.

Test vector `provenance.charon_ref` fields were deliberately **not** advanced:
that field records where a suite was generated, none of this drift changes an
expected value, and moving it without re-running the Go generators would assert
a verification that never happened.

### Correction made while doing the above

- `priority.md` claimed ties between equal-scoring priorities are broken "by
  their SSZ hash (deterministic, but arbitrary)". Wrong, and interop-relevant:
  charon breaks ties by **first-seen order over messages sorted by ascending peer
  ID** (`calculate.go` `SortStableFunc`). The hash sort applies to *topics*, which
  the same page already stated correctly one section earlier. An implementation
  following the old text would order priorities differently from charon.

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

   Rejection vectors (DONE, 2026-07-30) — three suites, promoted out of
   Aspirations. Every suite above passes by *producing a value*, which left the
   reject rules unpinned: an implementation could pass all six while accepting a
   128 MiB consensus message or a partial signature deposited into another
   operator's share slot. Under-rejecting is a DoS hole, over-rejecting breaks
   liveness against charon, and neither had a fixture.
   - [x] `test_vectors/qbft_msg_limits.json` — the Phase 1 QBFT hardening as
     accept/reject pairs either side of each boundary: justifications ≤ 2n,
     values ≤ 2(j+1), 32 MiB wire size. Each case names *which* limit fired,
     because charon checks justifications before values, so a message exceeding
     both is rejected for its justifications; two implementations that reject the
     same inputs for different reasons have not agreed on the protocol. The wire
     size is pinned as a **narrowing** of charon's 128 MiB libp2p default
     (`p2p/sender.go`), which consensus overrides — leaving the default in place
     accepts messages four times the permitted size. `source: spec`, because
     charon has no table test for `verifyMsgLimits`: the formulas are charon's,
     the choice of boundaries is not.
   - [x] `test_vectors/qbft_decided_resends.json` — charon's own
     `TestDecidedRebroadcastLimits` event sequences, with the expected rebroadcast
     decision per event rather than a total, so an implementation missing either
     half of the rule (strictly-increasing round, or the 16-per-source cap) fails a
     specific event. Counted as rebroadcast *events*, not messages, since the spec
     returns one message per peer where charon calls `Broadcast` once — a total
     would have encoded an implementation shape.
   - [x] `test_vectors/parsigex_sender_binding.json` — charon's
     `TestVerifyPeerShareIdx` table plus `TestNewExchangerRejectsIncompletePeerMap`.
     The peer map assigns share index 4 to the *second* peer, which is the case
     that separates a map-based implementation from a position-based one.

   The generator replays every charon-transcribed case through the spec and fails
   on disagreement, so these suites are charon's tables rather than the spec's
   opinion of them. `tests/test_vectors.py` builds each input from the case's own
   `input` object rather than sharing the generator's builders — a shared builder
   would let a wrong count agree with itself — and asserts each suite still carries
   both verdicts, since a suite that drifted to all-accept would pass every case
   while testing nothing.

   Versioned release artifacts (DONE, 2026-07-30) — the last piece of item 1, and
   the keystone for item 2, which pins "a spec release" rather than a commit.

   Decision (2026-07-30, Andrei): **spec semver plus a manifest**, not charon
   MAJOR.MINOR as this plan originally sketched. The sketch cannot hold: the spec
   tracks charon `main`, so it may specify behaviour no tagged charon carries — at
   `6054bcb2` three do — and a tag named `spec-v1.11` would claim to describe a
   charon that behaves differently. On that scheme no first release could be cut
   today at all. Instead the spec versions itself and the manifest states which
   charon it was validated against.

   - [x] `docs/versioning.md` — the policy: what bumps MAJOR/MINOR/PATCH, what an
     artifact contains, how a consumer reads the manifest, and how to cut a
     release. A **correction bumps MINOR, not PATCH**: when the spec said `peer_id`
     was field 2 of `PriorityMsg`, an implementation that followed it had to change
     its wire output, and calling that a fix does not make it compatible.
   - [x] `charon_anchor.json` gained `behaviours` — the machine-readable form of
     README's compatibility table, with the first charon release per behaviour
     (`null` for main-only). `tests/test_release.py` fails if the two disagree.
   - [x] `scripts/build_release.py` + `.github/workflows/release.yml` — builds
     `manifest.json` + `test_vectors/` + `proto/` (40 KiB tarball), attached to a
     published GitHub release. Runs on `release: published` rather than tag push,
     so a human decides a release happens and CI only builds what it ships, and it
     **fails if the tag and `pyproject.toml` disagree** — otherwise a release could
     ship a manifest naming a different version than the tag a consumer pinned.
     Docs are deliberately not in the artifact: a Go or Rust test cannot assert
     against Markdown.
   - [x] `pyproject.toml` version 0.0.1 → 0.1.0. **No tag was cut and nothing was
     published** — that is outward-facing and left to a human.

   Found by consuming the built artifact rather than by reading it: **charon's tags
   do not order lexically**, so `"v1.11.0" > "v1.9.0"` is false and a consumer
   filtering behaviours by string comparison silently concludes that v1.11.0
   behaviour is present on a v1.9.0 charon. The manifest therefore ships
   `first_charon_release_semver` as a `[major, minor, patch]` triple alongside the
   tag, and the policy page says to compare with it. Verified by walking the ladder
   against the extracted tarball: 7 behaviours absent on v1.7.1 (pluto's pin), 5 on
   v1.9.0. (The branch review then caught that `v1.11.0` names no existing release —
   only `v1.11.0-rc1` exists — so the timer fix and QBFT limits were moved to
   `first_charon_release: null` with notes naming the RC.)

2. **Consumer suites**: Go test package in charon + Rust test crate in pluto
   loading vectors from a pinned spec release. Catches charon regressions
   against its own documented protocol, not just pluto divergence.

   - [x] **Charon (Go), written and verified 2026-07-30.** In `consumers/go/`,
     laid out mirroring charon's tree so placing it is `rsync -a consumers/go/
     ~/charon/`. All nine suites, **314 subtests**, run green against a charon
     worktree at the anchor `6054bcb2`. Not a PR yet — this repo cannot merge into
     charon, so `consumers/README.md` documents placement and the pinning rules.
   - [x] **Pluto (Rust), written and verified 2026-08-01.** See
     `plans/pluto-conformance.md` and its Results table for the full
     per-suite verdicts against pluto commit `67088a2`.

   Correction to the plan's wording: it cannot be "a Go test package". Almost
   everything the vectors cover is unexported in charon — `hashProto`,
   `verifyMsgLimits`, `verifyPeerShareIdx`, `calculateResult`, the round-timer
   helpers, and the decided-resend limiter (a closure inside `Run`) — so an
   external package physically cannot reach them. The suite is one importable
   loader plus five in-package test files. `specvectors.CoveredSuites` records
   which file runs which suite, and `TestEverySuiteIsCovered` fails when a release
   ships a suite nothing runs; `tests/test_consumers.py` enforces the same
   mapping from this side, since the Go code is not compiled here.

   Found while writing it: **charon has two `hashProto` functions with different
   `Any` semantics.** `core/priority` hashes the `Any` wrapper itself, type URL
   included; `core/consensus/qbft` rejects an `Any` outright and its callers
   unwrap first, so the hash covers the inner message. The `any_string` vectors
   only round-trip through the priority one. The spec was right in both places —
   `encode_any_string` documents the type URL being inside the priority hash, and
   `hash_value` hashes the inner encoding for consensus — but the *contrast* was
   documented nowhere, and an implementation with one Any-hashing convention
   diverges on one side or the other.

   Verified by mutating charon rather than by asserting: `maxDecidedResends`
   16→15 fails `resend_cap_per_source`; the consensus wire limit 32→128 MiB fails
   `one_byte_over_limit` and `p2p_default_read_limit`; making priority's
   `hashProto` unwrap `Any` fails all four `any_string` cases.

   One coverage gap the mutation testing exposed, deliberately left open: moving
   priority's Any-hashing to the *call site* in `calculate.go` (unwrap there,
   leave `hashProto` alone) is **not** caught. The scoring vectors look topics up
   by name and no case pins the hash-derived *topic ordering*, so the convention
   is pinned for the function but not for its use. Closing it needs a vector that
   asserts topic order for two or more topics.
3. **Spec-conformance CI here** — split, because the two halves have different
   blockers:
   - [x] **Staleness alarm (DONE, 2026-07-30).** `charon_anchor.json` holds the
     pinned commit and the watched/ignored path sets in machine-readable form;
     `scripts/check_charon_drift.py` lists charon commits between the anchor and
     `main` that touch spec surface, exiting non-zero when any do;
     `.github/workflows/charon-staleness.yml` runs it weekly (Mondays 07:00 UTC)
     plus on demand. Not run on pull requests: charon drifting is not a reason to
     block an unrelated PR.

     Paths are watched **broadly** — whole directories, minus only the components
     listed under "Explicitly out of scope" below — so a charon subsystem nobody
     has considered gets reported rather than silently missed. Dependency bumps
     fall outside the watched roots and never fire. Test-only commits are
     reported but sorted last, since charon's tests are where the accept/reject
     tables this spec mirrors live, but they rarely move the wire.

     Verified by replay, not by assertion: run against the previous anchor
     `2eb6798e` it reproduces the Phase 1.1 findings exactly — the same three
     substantive commits ranked first, `adddef75` demoted to test-only,
     `7c0354f1` excluded as deadliner, and the three dependency bumps not matched
     at all. `tests/test_charon_anchor.py` pins the path-matching behaviour and
     fails if `charon_anchor.json` and the README anchor disagree, which would
     otherwise leave the check measuring drift from the wrong commit and still
     passing. The check is deliberately outside `tox`, since it needs the network.
   - [x] **Proto parity (DONE, 2026-07-30).** Promoted out of Aspirations, because
     `proto/` was the one part of the spec with no guardrail at all: nothing here
     compiles or executes it (the encoders in `encoding/` carry their own explicit
     field numbers), so a divergence was invisible to all 762 tests.
     `scripts/check_proto_parity.py` compares each file in `proto/` against the
     Charon file it mirrors — declared per file in `charon_anchor.json` — field by
     field: numbers, names, types, `repeated`/`optional` labels, `reserved` sets
     and the package. `.github/workflows/proto-parity.yml` runs it on any change
     to `proto/`, the mapping or the script.

     Not `buf breaking`, as originally sketched. `buf` diffs two revisions of one
     schema, but `proto/` is deliberately a *subset* of Charon's with different
     file paths and no `go_package`, so every legitimate omission would report as
     a breaking change. Omissions are instead declared with a reason and checked
     both ways: an undeclared one fails, and so does a declaration Charon has
     outgrown.

     Compares against the **anchor**, not `main`, so the result changes only when
     this repo does — that is what makes it safe on a pull request, where the
     staleness alarm would be noise. `scripts/charon_repo.py` now holds the anchor
     loader and git plumbing both checks share, so they cannot disagree about
     which commit the anchor is.
   - [ ] **Vector conformance against pinned checkouts**: checkout charon@pinned +
     pluto@pinned and run both vector suites. The charon half is now runnable —
     `consumers/go/` exists and passes — but running it from CI here means
     checking out charon, vendoring the artifact and invoking `go test`, which
     needs a Go toolchain in this repo's CI. Still blocked on item 2 for pluto.
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
- Charon's priority result ordering documented a tie-break by lowest peer ID but
  implemented it with Go's `slices.SortFunc`, which is **not stable**. It held
  only because Go's pdqsort falls back to insertion sort below 13 elements. The
  spec sorted stably and documented the divergence risk. **Resolved upstream** by
  charon #4611 (`6054bcb2`), which switched to `slices.SortStableFunc`; see
  Phase 1.1.
- The duty start delay is **integer division at nanosecond resolution**
  (`time.Duration`), so a 5s slot (Gnosis Chain) gives an attester delay of
  1666666666ns. The spec's float helper was silently 0.33ns off; there is now an
  integer-nanosecond API and the vectors are normative in integers.

From the proto parity pass (2026-07-30), all found by the new check on its first
run against charon `6054bcb2`:

- **`PriorityMsg` had `peer_id` and `topics` transposed** — the spec numbered them
  2 and 3, charon numbers them 3 and 2. Interop-fatal, and silent: both types are
  length-delimited, so a decoder does not error, it mis-parses. Worse, the message
  is signed over its own encoding, so an implementation following `proto/` would
  produce a signing root no peer can reproduce and *every* priority signature
  would fail. Nothing else in the repo caught it because no Python code encodes
  `PriorityMsg` — the field numbers only ever existed in the `.proto` file.
- **Seven of ten spec protos declared no `package`.** Not cosmetic: the package is
  part of the `Any` type URL, and priority and consensus both wrap payloads in
  `Any`. It also meant `core.corepb.v1.Duty`, referenced by three files, resolved
  to nothing.
- `bcast.proto` used `google.protobuf.Any` without importing it, so `proto/` was
  not compilable as it stood. The check now verifies imports and type resolution
  on the spec side alone, which needs no charon and so runs in `pytest`.
- `NodePubKeyMessage.shares` is `optional` in charon. For a message field that is
  presence semantics the wire already has, so this one was harmless — recorded
  because "harmless" was a conclusion the check forced someone to reach
  deliberately rather than an assumption.

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

- **Differential fuzzing**: random QBFT message sequences into spec-Python,
  charon-Go, pluto-Rust state machines; compare outputs.
- **Pluto link-back**: one-line PR to pluto README/AGENTS.md referencing this
  spec once Phase 1 lands ("read the spec; Go source is the reference impl").
- Quirks registry doc: still deferred, and now thinner — the priority slash was
  fixed upstream (Phase 1.1), leaving the dkg-sync trailing slash and the
  priority legacy alias, which is scheduled for removal in charon `v1.14`.

## Explicitly out of scope for the spec

Internal, non-wire-visible charon components: dutydb, aggsigdb, deadliner,
tracker (observability), parsigcache. Specify behaviorally only where
observable (e.g. the threshold that triggers aggregation).
