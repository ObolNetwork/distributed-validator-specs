---
name: pluto-conformance
description: Use when validating a pluto commit (or the latest pluto) against this repo's published conformance test vectors, when asked whether pluto still conforms to the spec, or when re-checking pluto after it upgrades its charon parity anchor.
---

# Pluto Conformance Validation

Run the Rust conformance harness (`consumers/rust/`) against a chosen pluto commit,
triage every divergence, and report a per-suite verdict. This skill is self-contained:
everything needed to run and triage is below — no other document is required.

**Scope: re-validate only.** The harness must already exist in the repo. If it does not,
stop and point at git history. If it no longer compiles against the chosen pluto,
that is an **API-drift finding** to report — never fix the harness, never weaken an
assertion, never modify pluto.

## Workflow

1. **Run the suites** (handles checkout/restore safely — do not improvise git commands
   against the pluto checkout):

   ```bash
   .claude/skills/pluto-conformance/scripts/run_suites.sh <commit-ish|latest> [output-dir]
   ```

   If the user names no commit, pass `latest`. The script aborts on a dirty pluto
   tree, puts `../pluto` on a detached checkout of the requested commit, runs one
   compile plus every suite, writes per-suite logs and `summary.tsv`
   (`suite <TAB> pass|fail|build-failed <TAB> log`), and restores the original pluto
   ref on exit — even on interrupt. Exit 0 means the run completed (test failures
   are data); a non-zero exit means an infrastructure error to relay verbatim.

2. **Compare against the baseline** (table below). At the baseline pluto commit
   `67088a2`, **every harness test is green** — known divergences are encoded as
   *pinned known-divergence tests* that pass while the divergence persists. Therefore:
   - All suites `pass` → every suite keeps its baseline verdict. Go to step 4.
   - Any suite `fail` or `build-failed` → pluto changed relative to the baseline
     (a pin flipped, new drift, or a regression). Go to step 3.

3. **Triage in parallel**: dispatch one sub-agent per red suite, all in a single
   message so they run concurrently, using the brief template below. Never triage by
   weakening the assertion; classify per the taxonomy and record.

4. **Report**: write `reports/pluto-conformance-<sha7>-<YYYY-MM-DD>.md` (the
   `reports/` dir is gitignored — local artifact, never committed) and print the same
   verdict table in chat. Include: pluto SHA tested, per-suite verdict + notes,
   findings (divergence, pluto file:line, ladder cover or not), and pin-flip callouts.

## Verdict taxonomy

A conformance check produces a **verdict**; a red case is a finding to record, never a
reason to change the test.

| Verdict | Meaning |
| --- | --- |
| `PASS` | Pluto reproduces every case in the group. |
| `FAIL` | Pluto diverges and no ladder entry excuses it — a real finding; consider reporting upstream to pluto. |
| `ABSENT-OK` | Divergence matches a `charon_anchor.json` → `behaviours` entry with `first_charon_release` > v1.7.1 (or `null`). The harness then **pins pluto's current behaviour** with a comment naming the ladder entry, so it flips loudly when pluto catches up. |
| `UNREACHABLE` | No public API path from an external crate; verified by code inspection with file:line recorded. A coverage gap, not a pass. |

## Ladder protocol

- Pluto pins parity to **charon v1.7.1**; the vectors describe charon main at the
  anchor commit recorded in `charon_anchor.json` (repo root).
- `charon_anchor.json` → `behaviours` lists specified behaviours that postdate v1.7.1.
  An entry with `first_charon_release` `null` (unreleased) or a release newer than
  v1.7.1 excuses a matching divergence as ABSENT-OK.
- If pluto moves its parity anchor past v1.7.1, ladder entries at or below the new
  anchor stop excusing divergences: the corresponding pinned tests should flip, and
  each flip is re-triaged (usually pluto catching up — flip the pin to the strict
  spec assertion; that is the one sanctioned kind of test change).

## Baseline: pluto `67088a2`, all harness tests green

| Suite | Baseline verdict | Pins and notes (what a flip means) |
| --- | --- | --- |
| `secp256k1_signatures` | PASS | Sign / recover / verify_65 via `pluto-k1util`. |
| `qbft_hashing` | FAIL (unsigned_data_set only) | 3 of 4 groups clean. Pin `unsigned_data_set_known_divergence_empty_map_entry_fields`: prost omits default-valued map-entry fields (empty key / empty value), charon's Go marshaler writes both — real interop FAIL, no ladder cover. Pin flip = pluto's encoding changed. |
| `bls_threshold` | PASS | Keys, partials, threshold aggregates, secret recovery, plain-aggregate non-verification. |
| `cluster_hashing` | FAIL (2 pinned cases) | Pins `definition_known_divergence_null_operators_and_validators` and `lock_known_divergence_missing_partial_deposit_data`: missing `#[serde(default)]` in pluto's `Definition`/`Lock` (rejects `null` operators/validators, missing `partial_deposit_data`; a masked `timestamp` blocker sits behind the first) — real FAIL, no ladder cover. `real_keys_3_of_4` full `verify_signatures` is asserted to stop at the EIP-712 stage (placeholder sigs) — coverage gap, documented not mocked. |
| `priority_scoring` | PASS | 18/18 end-to-end through `Prioritiser` over in-process libp2p. Pin: `PROTOCOL_ID == "charon/priority/2.0.0"` (legacy slash-less only; ladder "Preferred priority protocol ID", `null`). Flip = pluto added the preferred slash ID. |
| `timer_deadlines` | round_timeout PASS only with `Feature::ProposalTimeout` enabled; deadline ABSENT-OK; duty_start_delay UNREACHABLE | Default-config divergence pinned (`round_timeouts_pluto_default_feature_set`): proposer round-1 gives 1s not 1.5s — ABSENT-OK, ladder "Extended 1.5s proposer round-1 timeout (proposal_timeout)" (v1.9.0). Slot-invariance code pin (`round_timeout_is_duty_slot_invariant`) guards against timers growing slot dependence; deadline determinism is ladder "Deterministic (genesis-derived) eager double linear round deadlines" (v1.9.0). `delay_slot_offset` (`crates/core/src/scheduler.rs`) private → UNREACHABLE. |
| `qbft_msg_limits` | counts ABSENT-OK both directions; wire_size PASS | Pluto has neither the spec's `2n` justification cap nor any values cap; its own cap is `4 * nodes` (`MAX_JUSTIFICATIONS_PER_NODE = 4`, `crates/consensus/src/qbft/component.rs`) — pinned at boundary (`4n` accepted, `4n+1` rejects with `TooManyJustifications`). Ladder "QBFT DECIDED-resend rate limit and message size/count limits" (`null`). Wire size: 32 MiB `MAX_CONSENSUS_MSG_SIZE` enforced via `read_protobuf_with_max_size` — PASS. |
| `qbft_decided_resends` | ABSENT-OK | Pin reading holds: pluto rebroadcasts DECIDED on **every** post-decision ROUND-CHANGE from another source — no 16-per-source cap, no increasing-round dedup (`crates/core/src/qbft/mod.rs`). Same `null` ladder entry. Flip = pluto added a limiter → re-triage against the spec's expectations. |
| `parsigex_sender_binding` | cases ABSENT-OK; peer_map UNREACHABLE | `new_eth2_verifier`'s closure has no sender parameter — 2/6 cases pinned divergent (ladder "Sender-bound share indices in the DKG lock-hash exchange", `null`). Peer-map validation exists only in private code (`crates/dkg/src/frostp2p/transport.rs::validate_peer_share_indices`) or is position-derived (`Peer::share_idx`) → UNREACHABLE coverage gap (predates v1.7.1, no ladder cover). |
| `coverage` | — | Guard: published `test_vectors/*.json` must equal the covered-suite table. A fail here means a suite was added/removed — the harness needs a new test (out of this skill's scope; report it). |

## Known FAIL-class findings (recognize, don't re-derive)

1. **prost map-entry default-value omission** (`qbft_hashing`): pluto skips an empty
   string key / empty bytes value inside `UnsignedDataSet` map entries; charon always
   writes both. Reachable only via malformed/malicious wire input, but a real
   cross-implementation hash divergence.
2. **Missing `#[serde(default)]`** (`cluster_hashing`): pluto rejects verbatim
   charon artifacts with `null` operators/validators, an omitted
   `partial_deposit_data`, or an omitted `timestamp`. Real interop risk for tools
   handing pluto charon-produced JSON.

If a triage agent rediscovers one of these, it is the known finding, not news —
unless the pinned bytes/error changed, which is a pin flip.

## Triage sub-agent brief (template)

Dispatch one per red suite, in parallel:

> Triage a conformance divergence. Suite: `<suite>`. Pluto commit under test: `<sha>`
> (checkout at `../pluto` — read-only; never modify it). Captured test output:
> `<log path>`. Read the failing test in `consumers/rust/tests/<suite>.rs` to see
> what is asserted and which pins exist.
>
> Classify each failing case using this taxonomy: PASS / FAIL (no excuse) /
> ABSENT-OK (matches a `charon_anchor.json` → `behaviours` entry with
> `first_charon_release` > v1.7.1 or `null` — name the entry) / UNREACHABLE
> (no public API path; give file:line). Baseline expectation for this suite:
> `<baseline row>`. A failing *pinned known-divergence* test means pluto's behaviour
> CHANGED — describe the old pinned behaviour, the new behaviour, and whether pluto
> now matches the spec (likely caught up; ladder entry satisfied) or diverges a new
> way. Never propose weakening an assertion. Return: per-case verdict + one-paragraph
> note with pluto file:line evidence.

## Report format

```markdown
# Pluto conformance — <sha> — <date>

Pluto commit under test: `<full sha>` (requested: `<commit-ish arg>`)
Harness: consumers/rust @ <spec repo HEAD sha>

| Suite | Verdict | Notes |
| --- | --- | --- |
| ... one row per suite, plan-Results style ... |

## Findings
- <divergence, pluto file:line, ladder cover or not, new vs known>

## Pin flips
- <pinned test that changed behaviour, and what it means>
```

## Red flags — never do these

- Editing a test to make a red case green (the one exception: flipping a pin to the
  strict spec assertion after verifying pluto genuinely caught up — and only when the
  user asks for the fix, not during validation).
- Modifying anything in the pluto checkout, or leaving it on the tested commit
  (the script restores it; verify with `git -C ../pluto status` if a run was killed).
- Extrapolating verdicts from a partial run — report incomplete as incomplete.
- Committing `reports/` output or any changes made during validation.
