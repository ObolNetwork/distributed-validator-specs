# Pluto Conformance Skill — Design

Date: 2026-08-03
Status: approved

## Purpose

A project-level Claude Code skill (`/pluto-conformance [commit-ish]`) that validates a
pluto checkout against the published spec test vectors and reports a per-suite verdict.
It is **self-contained**: all knowledge needed to run and triage lives in the skill,
independent of `plans/pluto-conformance.md` (which may be deleted).

## Scope

**Re-validate only.** The skill assumes the Rust harness (`consumers/rust/`) exists in
the repo. It does not rebuild the harness and does not repair compile errors: if the
harness no longer compiles against the chosen pluto commit, that is itself reported as
an API-drift finding. Assertions are never weakened; pluto is never modified beyond a
temporary detached checkout.

## Interface

- Argument: any pluto commit-ish (hash, tag, branch). Default: `origin/<default-branch>`
  tip after a fetch ("latest").
- Preconditions, checked before touching anything: `~/pluto` exists and is clean
  (dirty tree aborts — never stash), `consumers/rust/` exists, cargo available.

## Components

```
.claude/skills/pluto-conformance/
├── SKILL.md            # workflow + all embedded triage knowledge
└── scripts/
    └── run_suites.sh   # checkout / run / restore, trap-guarded
```

### run_suites.sh `<commit-ish|latest>`

1. Refuse if `~/pluto` is dirty. Record the current ref (branch or detached SHA).
   Install a `trap ... EXIT` that restores it unconditionally (interrupt included).
2. `git fetch origin`; resolve the target; detached checkout.
3. Run `cargo test` once in `consumers/rust/` (one compile, all suites plus the
   coverage guard), capturing per-suite output to files in the session scratchpad.
4. Emit a machine-readable summary: resolved pluto SHA, and per suite pass/fail plus
   the path to its captured output.

### SKILL.md — embedded knowledge

Everything triage needs, independent of the plan document:

- **Verdict taxonomy**: PASS / FAIL / ABSENT-OK / UNREACHABLE, exact definitions.
- **Ladder protocol**: divergences triage against `charon_anchor.json` → `behaviours`;
  pluto pins charon v1.7.1; an entry with `first_charon_release` > v1.7.1 or `null`
  excuses a divergence as ABSENT-OK (and the harness pins pluto's current behaviour so
  the pin flips loudly when pluto catches up).
- **Baseline verdict table at pluto `67088a2`**: the nine suites' expected outcomes,
  naming the pinned known-divergence tests. A pin flip is news requiring re-triage,
  never assertion-weakening.
- **Known findings summary**: the two FAIL-class findings (prost map-entry
  default-value omission in `UnsignedDataSet` hashing; missing `#[serde(default)]`
  on `Definition`/`Lock` fields) and the ABSENT-OK set, so triage recognizes them.
- **Global constraints**: pluto never modified, red → triage → verdict → record,
  never weaken an assertion.
- **Triage sub-agent brief template**: given one suite's output, the ladder, and this
  knowledge, classify each divergence and return verdict + note.

## Flow

1. Run `run_suites.sh <commit>`.
2. Every suite matching its baseline outcome → keep baseline verdicts, go to report.
3. Any suite with unexpected output → fan out **one triage sub-agent per affected
   suite, in parallel**, each with the brief, that suite's captured output, and read
   access to the pluto checkout and `charon_anchor.json`. Compile failure = one
   API-drift finding covering the affected suites.
4. Write `reports/pluto-conformance-<sha>-<date>.md` (untracked — `reports/` is
   gitignored): pluto SHA tested, per-suite verdict table in the plan's Results
   style, findings, pin-flip callouts. Print the same table in chat.

## Error handling

- Dirty `~/pluto` → abort before any mutation.
- Unknown commit-ish after fetch → abort with the git error.
- Interrupted run → trap restores the ref; partial results reported as incomplete.
- Missing harness → abort, point at git history.

## Decisions taken

- Project-level skill (knowledge is repo-specific, travels with the repo).
- Detached checkout + restore in `~/pluto` (no worktree/path rewriting).
- One `cargo test` compile for the happy path; sub-agents only for triage.
- `reports/` is untracked and gitignored (local artifacts only).
