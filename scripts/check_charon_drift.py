"""Report Charon commits that touch spec surface since the pinned anchor.

This is the staleness alarm. The spec tracks Charon `main`, so it goes stale
silently: between 2026-07-14 and 2026-07-29 Charon moved eight commits past the
anchor, three of them wire-visible, and nothing noticed. Run this on a schedule
and the drift is a failing job instead of a discovery.

The anchor and the watched paths live in `charon_anchor.json`. Paths are watched
broadly and only the components the spec explicitly declines to cover are
ignored, so a Charon subsystem nobody has thought about yet is reported rather
than missed.

Usage:
    uv run python scripts/check_charon_drift.py
    uv run python scripts/check_charon_drift.py --repo-path ~/charon

Exits 0 when no watched path moved, 1 when something did (the alarm), and 2 when
the check itself could not run.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from charon_repo import (
    EXIT_ERROR,
    EXIT_FOUND,
    EXIT_OK,
    Anchor,
    CharonRepoError,
    resolve_repo,
    run_git,
)


@dataclass(frozen=True)
class Commit:
    """A Charon commit that touched at least one watched path."""

    sha: str
    subject: str
    watched_paths: tuple[str, ...]

    @property
    def is_test_only(self) -> bool:
        """Whether every watched path is a Go test file.

        Reported but deprioritised: a test-only change rarely moves the wire, and
        flagging it as loudly as a protocol change trains the reader to ignore
        the alarm. It is not filtered out, because Charon's tests are where the
        accept/reject tables this spec mirrors actually live.
        """
        return all(path.endswith("_test.go") for path in self.watched_paths)


def find_drift(anchor: Anchor, repo: Path) -> List[Commit]:
    """List commits between the anchor and the tracked branch touching spec surface."""
    if not run_git(["cat-file", "-t", anchor.commit], cwd=repo).strip() == "commit":
        raise CharonRepoError(f"anchor {anchor.commit} is not a commit in {anchor.repo}")

    # \x1e (record separator) cannot appear in a subject line, unlike newlines,
    # which --name-only already uses to separate paths.
    log = run_git(
        [
            "log",
            "--name-only",
            "--no-merges",
            "--format=\x1e%H%x1f%s",
            f"{anchor.commit}..origin/{anchor.branch}",
        ],
        cwd=repo,
    )

    commits: List[Commit] = []
    for record in log.split("\x1e"):
        if not record.strip():
            continue

        header, _, body = record.partition("\n")
        sha, _, subject = header.partition("\x1f")
        watched = tuple(
            line
            for line in (entry.strip() for entry in body.splitlines())
            if line and anchor.is_watched(line)
        )
        if watched:
            commits.append(Commit(sha=sha, subject=subject, watched_paths=watched))

    # Protocol changes first; test-only noise last.
    return sorted(commits, key=lambda commit: commit.is_test_only)


def format_report(anchor: Anchor, commits: Sequence[Commit], head: str) -> str:
    """Render the drift report as Markdown, for a terminal or a job summary."""
    lines = [
        "# Charon staleness check",
        "",
        f"- Anchor: `{anchor.commit[:8]}` ({anchor.date})",
        f"- Charon `{anchor.branch}`: `{head[:8]}`",
        "",
    ]

    if not commits:
        lines.append("No commits touching spec surface. The anchor is current.")
        return "\n".join(lines)

    substantive = [commit for commit in commits if not commit.is_test_only]
    lines.append(
        f"**{len(commits)} commit(s) touch spec surface"
        f"{f', {len(substantive)} outside tests' if substantive else ', all test-only'}.**"
    )
    lines.append("")

    for commit in commits:
        marker = " _(tests only)_" if commit.is_test_only else ""
        lines.append(f"- `{commit.sha[:8]}` {commit.subject}{marker}")
        for path in commit.watched_paths:
            lines.append(f"    - `{path}`")

    lines += [
        "",
        "Re-validate the affected specs against Charon, then advance `commit` in",
        "`charon_anchor.json` and the version anchor in `README.md`. Record what",
        "moved, and what was assessed and ruled out of scope, in",
        "`plans/spec-completion.md`.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument(
        "--repo-path",
        default=os.environ.get("CHARON_REPO_PATH"),
        help="Existing Charon checkout to use instead of cloning (env: CHARON_REPO_PATH)",
    )
    args = parser.parse_args(argv)

    stack: List[Path] = []
    try:
        anchor = Anchor.load()
        repo = resolve_repo(anchor, args.repo_path, stack)
        head = run_git(["rev-parse", f"origin/{anchor.branch}"], cwd=repo).strip()
        commits = find_drift(anchor, repo)
    except CharonRepoError as error:
        print(f"charon drift check could not run: {error}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        for path in stack:
            shutil.rmtree(path, ignore_errors=True)

    report = format_report(anchor, commits, head)
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    return EXIT_FOUND if commits else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
