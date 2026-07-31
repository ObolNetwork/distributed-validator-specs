"""Guard the pinned Charon anchor and the paths the staleness check watches.

`charon_anchor.json` is the machine-readable half of a fact that README.md also
states in prose. If they disagree, the staleness check silently measures drift
from the wrong commit — it would still pass, which is the failure mode worth a
test. `scripts/check_charon_drift.py` and `scripts/check_proto_parity.py` both
consume it through `scripts/charon_repo.py`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR_PATH = REPO_ROOT / "charon_anchor.json"
README_PATH = REPO_ROOT / "README.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from charon_repo import Anchor, CharonRepoError  # noqa: E402


@pytest.fixture(scope="module")
def anchor() -> Anchor:
    return Anchor.load(ANCHOR_PATH)


def test_anchor_commit_is_a_full_sha(anchor: Anchor) -> None:
    # A short SHA would still resolve in git but makes the README comparison
    # below ambiguous, and abbreviations can collide as a repository grows.
    assert re.fullmatch(r"[0-9a-f]{40}", anchor.commit)


def test_readme_states_the_same_anchor(anchor: Anchor) -> None:
    readme = README_PATH.read_text()

    assert f"`{anchor.commit[:8]}`" in readme, (
        f"README.md must name the anchor commit {anchor.commit[:8]}; "
        "advance both together or the staleness check measures from the wrong commit"
    )
    assert anchor.date in readme, f"README.md must name the anchor date {anchor.date}"


def test_watch_and_ignore_paths_are_repo_relative(anchor: Anchor) -> None:
    for path in (*anchor.watch_paths, *anchor.ignore_paths):
        assert path, "empty path would match everything"
        assert not path.startswith("/"), f"{path} must be repository-relative"
        assert ".." not in path, f"{path} must not escape the repository"


def test_every_ignore_path_falls_under_a_watch_path(anchor: Anchor) -> None:
    # An ignore entry outside the watched set is dead configuration: it excludes
    # nothing, and reads as coverage that was considered when it was not.
    orphans = [
        path
        for path in anchor.ignore_paths
        if not any(path.startswith(prefix) for prefix in anchor.watch_paths)
    ]

    assert not orphans, f"ignore_paths not under any watch_path: {orphans}"


@pytest.mark.parametrize(
    "path",
    [
        "core/parsigex/parsigex.go",
        "core/priority/prioritiser.go",
        "core/consensus/qbft/msg.go",
        "cluster/ssz.go",
        "dkg/exchanger.go",
        "p2p/sender.go",
        "app/peerinfo/peerinfo.go",
    ],
)
def test_spec_surface_is_watched(anchor: Anchor, path: str) -> None:
    assert anchor.is_watched(path)


@pytest.mark.parametrize(
    "path",
    [
        # The components plans/spec-completion.md declares out of scope.
        "core/deadline.go",
        "core/dutydb/dutydb.go",
        "core/aggsigdb/memory.go",
        "core/tracker/tracker.go",
        # Outside the watched roots entirely: this is what keeps dependency
        # bumps, which touch only go.mod and go.sum, from firing the alarm.
        "go.mod",
        "go.sum",
        "docs/configuration.md",
        "testutil/beaconmock/beaconmock.go",
    ],
)
def test_out_of_scope_paths_are_not_watched(anchor: Anchor, path: str) -> None:
    assert not anchor.is_watched(path)


def test_ignored_file_does_not_shadow_its_directory(anchor: Anchor) -> None:
    # `core/deadline.go` is ignored inside a watched `core/`, so prefix matching
    # must not let the ignore entry swallow neighbours that merely share a stem.
    assert not anchor.is_watched("core/deadline.go")
    assert anchor.is_watched("core/deadliner_that_does_not_exist.go")
    # A file entry is an exact match, not a prefix: a neighbour that extends the
    # ignored name is still watched.
    assert anchor.is_watched("core/deadline.gogen")


def test_malformed_anchor_raises_the_check_error(tmp_path: Path) -> None:
    # Both check scripts distinguish "could not run" (exit 2) from "found
    # something" (exit 1) by catching CharonRepoError; a raw JSON or key error
    # would escape as exit 1 and read as a real finding.
    not_json = tmp_path / "anchor.json"
    not_json.write_text("{ this is not json")

    with pytest.raises(CharonRepoError, match="cannot load anchor"):
        Anchor.load(not_json)

    missing_key = tmp_path / "incomplete.json"
    missing_key.write_text(json.dumps({"repo": "x", "branch": "main"}))

    with pytest.raises(CharonRepoError, match="cannot load anchor"):
        Anchor.load(missing_key)


def test_anchor_file_is_sorted_and_deduplicated() -> None:
    # Kept sorted so a future edit is a one-line diff rather than a reshuffle.
    data = json.loads(ANCHOR_PATH.read_text())

    for key in ("watch_paths", "ignore_paths"):
        paths = data[key]
        assert paths == sorted(paths), f"{key} must be sorted"
        assert len(paths) == len(set(paths)), f"{key} must not repeat a path"
