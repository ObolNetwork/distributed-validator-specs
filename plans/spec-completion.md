# Spec Completion Plan

Status as of 2026-07-16. Goal: make this repo a formal spec of the Obol DV
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

## Phase 1 — Un-stale (DONE, this PR)

- [x] `MsgSync.nickname` field 6 (charon #4105, in v1.9.5)
- [x] Deterministic genesis/slot-derived deadlines + duty start delay in
      `DoubleEagerLinearRoundTimer` (charon #4243, in v1.9.5)
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

## Phase 2 — Close interop-critical gaps (next commit / next session)

Priority order:

1. **FROST DKG** (top priority — pluto's near-term DKG target, and charon's
   default scheme; the spec currently only covers opt-in Pedersen):
   - Protocol ID `/charon/dkg/frost/2.0.0/` (note trailing slash)
   - Executable message models mirroring `dkg/dkgpb/v1/frost.proto`
     (round 1/round 2 casts, share exchange)
   - Flow spec from charon `dkg/frost.go` + `dkg/frostp2p.go`
     (`runFrostParallel`)
   - Node signature exchange: `/charon/dkg/node_sig` (`dkg/nodesigs.go`)
   - Doc page `docs/dv-spec/dkg-frost.md`; mark Pedersen as the non-default
     alternative in README/docs
2. **sigagg**: BLS threshold aggregation spec — partial sig verification
   rules, parsigdb threshold trigger, aggregate construction
   (`core/sigagg`, `tbls`)
3. **infosync**: the actual use of the priority protocol — topics
   (version/protocol/proposal), how the result selects the cluster-wide
   consensus protocol (`core/infosync`). Pluto needs this for its
   ConsensusController work (pluto issue #402 part B)
4. **DKG reshare / add / remove / replace operator flows**
   (`dkg/protocol_*.go`) — wire-visible, growing surface
5. **validatorapi conformance**: endpoint-by-endpoint behavior deltas vs a
   plain beacon node (what charon intercepts/rewrites/aggregates)
6. Prose specs: scheduler duty timing (slot offsets feed the timer spec),
   core/bcast (beacon broadcast + recast)
7. Cluster definition v1.11 (when we move the target past v1.10)

## Phase 3 — Conformance testing (subsequent sessions)

1. **Spec-generated test vectors** (`test_vectors/`, JSON): QBFT message
   hashing/signing (replace pluto's charon-generated
   `crates/consensus/testdata/vectors/hashproto.json` as source of truth),
   priority scoring, timer deadline tables (genesis, slot, duty type →
   round deadlines), DKG transcripts, cluster lock hash/sig cases.
   Publish as versioned release artifacts.
2. **Consumer suites**: Go test package in charon + Rust test crate in pluto
   loading vectors from a pinned spec release. Catches charon regressions
   against its own documented protocol, not just pluto divergence.
3. **Spec-conformance CI here**: checkout charon@pinned + pluto@pinned, run
   both vector suites; scheduled weekly run against charon@main as the
   staleness alarm.
4. **Wire-level harness**: extend pluto's mixed docker-compose/dkg-runner
   infra; spec Python as passive protocol oracle (decode captured protobuf,
   validate QBFT transcripts against `protocol.py`).

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
