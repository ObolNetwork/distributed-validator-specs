"""Shared access to the pinned Charon checkout described by `charon_anchor.json`.

Two checks read that anchor and ask different questions of it:

- `check_charon_drift.py` — what moved in Charon *since* the anchor?
- `check_proto_parity.py` — does this repo's `proto/` still match Charon *at* the
  anchor?

They have to agree on which commit the anchor is, so the loader and the git
plumbing live here rather than being written twice.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR_PATH = REPO_ROOT / "charon_anchor.json"

# Shared exit convention: 0 nothing to report, 1 the check found something (the
# alarm), 2 the check itself could not run. The middle case has to be distinct
# from the last one, or a network failure reads as a clean spec.
EXIT_OK = 0
EXIT_FOUND = 1
EXIT_ERROR = 2


class CharonRepoError(RuntimeError):
    """The check or build could not be completed, as distinct from a check finding something."""


@dataclass(frozen=True)
class ProtoPair:
    """A spec `.proto` file and the Charon file it mirrors."""

    spec: str
    charon: str
    not_mirrored: tuple[str, ...]
    why_not_mirrored: str


@dataclass(frozen=True)
class Behaviour:
    """A specified behaviour and the first Charon release that carried it.

    `first_charon_release` is None for behaviour that no final Charon release
    carries — it may exist only on Charon `main`, or in release candidates; the
    entry's note says which. A consumer running a released Charon must not
    expect to interoperate with such behaviour yet.
    """

    name: str
    first_charon_release: str | None
    spec: str
    note: str

    @property
    def released(self) -> bool:
        """Whether any tagged Charon release carries this behaviour."""
        return self.first_charon_release is not None

    @property
    def semver(self) -> tuple[int, int, int] | None:
        """`first_charon_release` as a comparable triple, or None if unreleased.

        Charon's tags do not compare correctly as strings: `"v1.11.0" > "v1.9.0"`
        is False, because `"1" < "9"` at the third character. Every consumer
        deciding "is this behaviour in the Charon I run?" needs that comparison,
        so the manifest ships the triple rather than leaving each of them to
        rediscover the trap.
        """
        if self.first_charon_release is None:
            return None

        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", self.first_charon_release)
        if match is None:
            raise CharonRepoError(
                f"behaviour {self.name!r} has unparsable release "
                f"{self.first_charon_release!r}; expected vMAJOR.MINOR.PATCH"
            )

        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch)


@dataclass(frozen=True)
class Anchor:
    """The pinned Charon commit and the paths that matter to this spec."""

    repo: str
    branch: str
    commit: str
    date: str
    watch_paths: tuple[str, ...]
    ignore_paths: tuple[str, ...]
    protos: tuple[ProtoPair, ...]
    behaviours: tuple[Behaviour, ...]

    @classmethod
    def load(cls, path: Path = ANCHOR_PATH) -> Anchor:
        """Read the anchor from its JSON file.

        Raises:
            CharonRepoError: If the file is unreadable, is not JSON, or lacks a
                required key. Wrapped so a broken anchor exits as "the check
                could not run" rather than as a finding.
        """
        try:
            data = json.loads(path.read_text())
            return cls._parse(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise CharonRepoError(f"cannot load anchor {path}: {error!r}") from error

    @classmethod
    def _parse(cls, data: dict[str, Any]) -> Anchor:
        return cls(
            repo=data["repo"],
            branch=data["branch"],
            commit=data["commit"],
            date=data["date"],
            watch_paths=tuple(data["watch_paths"]),
            ignore_paths=tuple(data["ignore_paths"]),
            protos=tuple(
                ProtoPair(
                    spec=entry["spec"],
                    charon=entry["charon"],
                    not_mirrored=tuple(entry.get("not_mirrored", ())),
                    why_not_mirrored=entry.get("why_not_mirrored", ""),
                )
                for entry in data["protos"]
            ),
            behaviours=tuple(
                Behaviour(
                    name=entry["name"],
                    first_charon_release=entry["first_charon_release"],
                    spec=entry["spec"],
                    note=entry.get("note", ""),
                )
                for entry in data["behaviours"]
            ),
        )

    def is_watched(self, path: str) -> bool:
        """Whether a changed file is spec surface.

        `ignore_paths` wins over `watch_paths`, which is how a single ignored file
        inside a watched directory (`core/deadline.go`) is expressed.
        """
        if not any(_covers(path, prefix) for prefix in self.watch_paths):
            return False

        return not any(_covers(path, prefix) for prefix in self.ignore_paths)


def _covers(path: str, prefix: str) -> bool:
    """Whether a watch or ignore entry covers a changed file.

    A directory entry (trailing `/`) covers everything under it. A file entry
    covers exactly that file — a bare `startswith` would also match
    `core/deadline.gogen`, silently widening an ignore to its neighbours.
    """
    if prefix.endswith("/"):
        return path.startswith(prefix)

    return path == prefix or path.startswith(prefix + "/")


def run_git(args: Sequence[str], cwd: Path | None = None) -> str:
    """Run a git command and return its stdout, raising on a non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CharonRepoError(f"git {' '.join(args)} failed: {result.stderr.strip()}")

    return result.stdout


def clone_charon(anchor: Anchor, destination: Path) -> Path:
    """Clone Charon without blob content.

    `--filter=blob:none` keeps the full commit and tree history, which is what
    `git log --name-only` needs, while skipping file contents. A `git show` of a
    specific file still works: the blob is fetched on demand. A shallow clone
    would not work at all, since the anchor can be arbitrarily far back.
    """
    run_git(
        [
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--quiet",
            anchor.repo,
            str(destination),
        ]
    )
    return destination


def resolve_repo(anchor: Anchor, repo_path: str | None, stack: List[Path]) -> Path:
    """Return a Charon repository to inspect, cloning one if none was supplied.

    A supplied checkout is used as-is: the parity check only reads the pinned
    anchor commit, so it must work offline and must not touch the checkout's
    refs. A check that needs the current branch head fetches it explicitly with
    `fetch_branch_head`.

    Any directory created is appended to `stack` for the caller to clean up.
    """
    if repo_path:
        path = Path(repo_path).expanduser().resolve()
        if not (path / ".git").exists():
            raise CharonRepoError(f"{path} is not a git repository")

        return path

    temporary = Path(tempfile.mkdtemp(prefix="charon-drift-"))
    stack.append(temporary)
    return clone_charon(anchor, temporary / "charon")


def fetch_branch_head(anchor: Anchor, repo: Path) -> str:
    """Fetch the tracked branch from the anchor's repository URL and return its sha.

    Fetching from `anchor.repo` rather than `origin` matters for a local
    checkout: its `origin` can point at a fork whose branch is arbitrarily
    stale, and measuring drift against a stale fork reports a clean spec that
    is anything but. `FETCH_HEAD` is plain fetch metadata, so the checkout's
    own remote-tracking refs are left untouched.
    """
    run_git(["fetch", "--quiet", anchor.repo, anchor.branch], cwd=repo)
    return run_git(["rev-parse", "FETCH_HEAD"], cwd=repo).strip()


def read_file_at(repo: Path, commit: str, path: str) -> str:
    """Read one file's contents at a specific commit, without checking anything out."""
    try:
        return run_git(["show", f"{commit}:{path}"], cwd=repo)
    except CharonRepoError as error:
        raise CharonRepoError(f"cannot read {path} at {commit[:8]}: {error}") from error
