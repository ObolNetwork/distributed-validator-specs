#!/usr/bin/env bash
# Run the spec's Rust conformance harness against a chosen pluto commit.
#
# Usage: run_suites.sh <commit-ish|latest> [output-dir]
#
#   commit-ish  Any pluto commit, tag, or branch. "latest" means the tip of
#               origin's default branch after a fetch.
#   output-dir  Where per-suite logs and summary.tsv land (default: mktemp -d).
#
# The pluto checkout (sibling of this repo, ../pluto) is put on a detached
# checkout of the requested commit for the duration of the run and restored
# unconditionally on exit, including on interrupt. A dirty pluto tree aborts
# before anything is touched.
#
# Exit codes: 0 = run completed (test failures are data, see summary.tsv);
#             non-zero = infrastructure error (dirty tree, bad commit, missing dirs).
#
# summary.tsv columns: suite <TAB> pass|fail|build-failed <TAB> log-path
# The resolved pluto SHA is written to pluto_sha.txt and echoed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
# Not configurable: the harness Cargo.toml hard-codes path dependencies to this
# sibling checkout, so testing any other location would silently compile the wrong code.
PLUTO_DIR="$(cd "$REPO_ROOT/.." && pwd)/pluto"
HARNESS_DIR="$REPO_ROOT/consumers/rust"

TARGET="${1:?usage: run_suites.sh <commit-ish|latest> [output-dir]}"
OUT_DIR="${2:-$(mktemp -d)}"
mkdir -p "$OUT_DIR"

fail() { echo "error: $*" >&2; exit 1; }

[ -e "$PLUTO_DIR/.git" ] || fail "pluto checkout not found at $PLUTO_DIR"
[ -f "$HARNESS_DIR/Cargo.toml" ] || fail "harness not found at $HARNESS_DIR (re-validate-only skill; see git history)"
command -v cargo >/dev/null || fail "cargo not on PATH"

# Never touch a dirty pluto tree.
if [ -n "$(git -C "$PLUTO_DIR" status --porcelain)" ]; then
  fail "pluto working tree at $PLUTO_DIR is dirty; commit or stash it yourself first"
fi

# Record where pluto is now (branch name, or SHA if already detached),
# and restore it no matter how this script exits.
ORIG_REF="$(git -C "$PLUTO_DIR" symbolic-ref -q --short HEAD || git -C "$PLUTO_DIR" rev-parse HEAD)"
restore() { git -C "$PLUTO_DIR" checkout -q "$ORIG_REF" || echo "warning: failed to restore pluto to $ORIG_REF" >&2; }
trap restore EXIT

git -C "$PLUTO_DIR" fetch -q origin

if [ "$TARGET" = "latest" ]; then
  DEFAULT_BRANCH="$(git -C "$PLUTO_DIR" symbolic-ref -q --short refs/remotes/origin/HEAD || true)"
  if [ -z "$DEFAULT_BRANCH" ]; then
    git -C "$PLUTO_DIR" remote set-head origin -a >/dev/null
    DEFAULT_BRANCH="$(git -C "$PLUTO_DIR" symbolic-ref --short refs/remotes/origin/HEAD)"
  fi
  TARGET="$DEFAULT_BRANCH"
fi

SHA="$(git -C "$PLUTO_DIR" rev-parse --verify "${TARGET}^{commit}")" \
  || fail "cannot resolve pluto commit-ish '$TARGET'"
git -C "$PLUTO_DIR" checkout -q --detach "$SHA"
echo "$SHA" > "$OUT_DIR/pluto_sha.txt"
echo "pluto under test: $SHA"

SUMMARY="$OUT_DIR/summary.tsv"
: > "$SUMMARY"

# One compile for everything; a build failure against the new pluto is an
# API-drift finding covering every suite, not something to fix here.
if ! (cd "$HARNESS_DIR" && cargo test --no-run) > "$OUT_DIR/build.log" 2>&1; then
  for t in "$HARNESS_DIR"/tests/*.rs; do
    printf '%s\tbuild-failed\t%s\n' "$(basename "$t" .rs)" "$OUT_DIR/build.log" >> "$SUMMARY"
  done
  echo "build failed against $SHA — see $OUT_DIR/build.log"
  cat "$SUMMARY"
  exit 0
fi

for t in "$HARNESS_DIR"/tests/*.rs; do
  suite="$(basename "$t" .rs)"
  log="$OUT_DIR/$suite.log"
  if (cd "$HARNESS_DIR" && cargo test --test "$suite") > "$log" 2>&1; then
    status=pass
  else
    status=fail
  fi
  printf '%s\t%s\t%s\n' "$suite" "$status" "$log" >> "$SUMMARY"
done

echo "summary: $SUMMARY"
cat "$SUMMARY"
