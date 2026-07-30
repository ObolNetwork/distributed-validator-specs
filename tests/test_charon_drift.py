"""Guard the drift check's git plumbing, offline.

The staleness alarm's dangerous failure is the inverse of its purpose: a
parsing or filtering regression that prints "the anchor is current" while
watched files moved, as a green scheduled job. A synthetic repository pins the
behaviours a live Charon clone cannot exercise deterministically — renames out
of the watched surface, ignored files, test-only ordering — and the exit-code
contract the CI workflow depends on.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_charon_drift as drift  # noqa: E402
from charon_repo import (  # noqa: E402
    EXIT_ERROR,
    EXIT_FOUND,
    EXIT_OK,
    Anchor,
    CharonRepoError,
    fetch_branch_head,
    resolve_repo,
    run_git,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def commit_all(repo: Path, subject: str) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "-qm", subject)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def charon_like(tmp_path: Path) -> tuple[Anchor, Path]:
    """A tiny repository shaped like Charon: a watched dir holding one ignored file.

    The anchor's `repo` is the repository's own path, so fetching from the
    anchor URL works without a network and without any `origin` remote — which
    is itself the property under test: the drift check must not depend on where
    a local checkout's `origin` points.
    """
    repo = tmp_path / "charon"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")

    (repo / "core").mkdir()
    (repo / "core" / "qbft.go").write_text("package core\n")
    (repo / "core" / "deadline.go").write_text("package core\n")
    anchor_sha = commit_all(repo, "anchor")

    anchor = Anchor(
        repo=str(repo),
        branch="main",
        commit=anchor_sha,
        date="2026-01-01",
        watch_paths=("core/",),
        ignore_paths=("core/deadline.go",),
        protos=(),
        behaviours=(),
    )
    return anchor, repo


def test_watched_change_is_reported(charon_like: tuple[Anchor, Path]) -> None:
    anchor, repo = charon_like
    (repo / "core" / "qbft.go").write_text("package core // changed\n")
    sha = commit_all(repo, "core: change qbft")

    commits = drift.find_drift(anchor, repo, head=sha)

    assert [commit.sha for commit in commits] == [sha]
    assert commits[0].subject == "core: change qbft"
    assert commits[0].watched_paths == ("core/qbft.go",)


def test_rename_out_of_the_watched_surface_is_reported(
    charon_like: tuple[Anchor, Path],
) -> None:
    # git log detects renames by default and lists only the destination path,
    # so without --no-renames a restructure that moves a watched file to an
    # unwatched directory reports as "no drift" — the exact silence the check
    # exists to prevent.
    anchor, repo = charon_like
    (repo / "internal").mkdir()
    (repo / "core" / "qbft.go").rename(repo / "internal" / "qbft.go")
    sha = commit_all(repo, "restructure: move qbft out of core")

    commits = drift.find_drift(anchor, repo, head=sha)

    assert [commit.sha for commit in commits] == [sha]
    assert "core/qbft.go" in commits[0].watched_paths


def test_ignored_file_changes_are_not_reported(charon_like: tuple[Anchor, Path]) -> None:
    anchor, repo = charon_like
    (repo / "core" / "deadline.go").write_text("package core // changed\n")
    sha = commit_all(repo, "core: change the ignored deadliner")

    assert drift.find_drift(anchor, repo, head=sha) == []


def test_substantive_commits_sort_before_test_only_ones(
    charon_like: tuple[Anchor, Path],
) -> None:
    anchor, repo = charon_like
    (repo / "core" / "qbft_test.go").write_text("package core\n")
    test_sha = commit_all(repo, "core: test-only change")
    (repo / "core" / "qbft.go").write_text("package core // changed\n")
    code_sha = commit_all(repo, "core: substantive change")

    commits = drift.find_drift(anchor, repo, head=code_sha)

    assert [commit.sha for commit in commits] == [code_sha, test_sha]
    assert [commit.is_test_only for commit in commits] == [False, True]


def test_anchor_that_is_not_a_commit_is_an_error(charon_like: tuple[Anchor, Path]) -> None:
    anchor, repo = charon_like
    blob = git(repo, "rev-parse", f"{anchor.commit}:core/qbft.go")
    bad = Anchor(
        repo=anchor.repo,
        branch=anchor.branch,
        commit=blob,
        date=anchor.date,
        watch_paths=anchor.watch_paths,
        ignore_paths=anchor.ignore_paths,
        protos=(),
        behaviours=(),
    )

    with pytest.raises(CharonRepoError, match="is not a commit"):
        drift.find_drift(bad, repo, head=anchor.commit)


def test_fetch_branch_head_uses_the_anchor_url_not_origin(
    charon_like: tuple[Anchor, Path],
) -> None:
    # The fixture repository has no `origin` at all: resolving the branch tip
    # must go through anchor.repo, or a local checkout whose origin points at a
    # stale fork would measure drift against the wrong repository.
    anchor, repo = charon_like
    (repo / "core" / "qbft.go").write_text("package core // moved on\n")
    tip = commit_all(repo, "core: move past the anchor")

    assert fetch_branch_head(anchor, repo) == tip


def test_resolve_repo_uses_a_supplied_checkout_as_is(
    charon_like: tuple[Anchor, Path],
) -> None:
    anchor, repo = charon_like
    stack: list[Path] = []

    assert resolve_repo(anchor, str(repo), stack) == repo
    assert stack == [], "a supplied checkout must not schedule a cleanup"


def test_resolve_repo_rejects_a_non_repository(tmp_path: Path) -> None:
    anchor = Anchor(
        repo="https://example.invalid/charon",
        branch="main",
        commit="0" * 40,
        date="2026-01-01",
        watch_paths=(),
        ignore_paths=(),
        protos=(),
        behaviours=(),
    )

    with pytest.raises(CharonRepoError, match="is not a git repository"):
        resolve_repo(anchor, str(tmp_path), [])


def test_run_git_raises_on_failure(tmp_path: Path) -> None:
    with pytest.raises(CharonRepoError, match="git rev-parse"):
        run_git(["rev-parse", "not-a-real-ref"], cwd=tmp_path)


def test_main_maps_results_to_the_exit_contract(
    charon_like: tuple[Anchor, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exit code is the whole interface with the scheduled workflow: findings
    # printed but exit 0 is a green job and a silent spec.
    anchor, repo = charon_like
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(drift, "resolve_repo", lambda anchor, path, stack: repo)
    monkeypatch.setattr(drift, "fetch_branch_head", lambda anchor, repo: anchor.commit)

    monkeypatch.setattr(drift, "find_drift", lambda anchor, repo, head: [])
    assert drift.main([]) == EXIT_OK

    found = [drift.Commit(sha="a" * 40, subject="core: change", watched_paths=("core/x.go",))]
    monkeypatch.setattr(drift, "find_drift", lambda anchor, repo, head: found)
    assert drift.main([]) == EXIT_FOUND

    def unreachable(anchor: Anchor, repo: Path) -> str:
        raise CharonRepoError("network unreachable")

    monkeypatch.setattr(drift, "fetch_branch_head", unreachable)
    assert drift.main([]) == EXIT_ERROR
