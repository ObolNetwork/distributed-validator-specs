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
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR_PATH = REPO_ROOT / "charon_anchor.json"

# Shared exit convention: 0 nothing to report, 1 the check found something (the
# alarm), 2 the check itself could not run. The middle case has to be distinct
# from the last one, or a network failure reads as a clean spec.
EXIT_OK = 0
EXIT_FOUND = 1
EXIT_ERROR = 2


class CharonRepoError(RuntimeError):
    """The check could not be completed, as distinct from finding something."""


@dataclass(frozen=True)
class ProtoPair:
    """A spec `.proto` file and the Charon file it mirrors."""

    spec: str
    charon: str
    not_mirrored: tuple[str, ...]
    why_not_mirrored: str


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

    @classmethod
    def load(cls, path: Path = ANCHOR_PATH) -> Anchor:
        """Read the anchor from its JSON file."""
        data = json.loads(path.read_text())
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
        )

    def is_watched(self, path: str) -> bool:
        """Whether a changed file is spec surface.

        `ignore_paths` wins over `watch_paths`, which is how a single ignored file
        inside a watched directory (`core/deadline.go`) is expressed.
        """
        if not any(path.startswith(prefix) for prefix in self.watch_paths):
            return False

        return not any(path == prefix or path.startswith(prefix) for prefix in self.ignore_paths)


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

    Any directory created is appended to `stack` for the caller to clean up.
    """
    if repo_path:
        path = Path(repo_path).expanduser().resolve()
        if not (path / ".git").exists():
            raise CharonRepoError(f"{path} is not a git repository")

        # A local checkout can be on any branch and arbitrarily out of date.
        run_git(["fetch", "--quiet", "origin", anchor.branch], cwd=path)
        return path

    temporary = Path(tempfile.mkdtemp(prefix="charon-drift-"))
    stack.append(temporary)
    return clone_charon(anchor, temporary / "charon")


def read_file_at(repo: Path, commit: str, path: str) -> str:
    """Read one file's contents at a specific commit, without checking anything out."""
    try:
        return run_git(["show", f"{commit}:{path}"], cwd=repo)
    except CharonRepoError as error:
        raise CharonRepoError(f"cannot read {path} at {commit[:8]}: {error}") from error
