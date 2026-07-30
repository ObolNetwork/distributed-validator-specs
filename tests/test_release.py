"""Guard the release manifest and the version policy it encodes.

A release is the artifact another implementation pins, so the failure that
matters is a manifest that misdescribes what it ships: a version that disagrees
with the tag, a compatibility table that has drifted from README.md, or an
unreleased behaviour with no guidance on what to do instead. Each of those would
still produce a well-formed artifact.

See `docs/versioning.md` for the policy itself.
"""

from __future__ import annotations

import copy
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_release import (  # noqa: E402
    VERSION_RE,
    build,
    build_manifest,
    spec_version,
    tag_for,
    verify,
)
from charon_repo import Anchor, CharonRepoError  # noqa: E402


@pytest.fixture(scope="module")
def anchor() -> Anchor:
    return Anchor.load()


@pytest.fixture(scope="module")
def manifest(anchor: Anchor) -> Dict[str, Any]:
    return build_manifest(spec_version(), anchor)


# --- the version policy -----------------------------------------------------


def test_spec_version_is_semver() -> None:
    assert VERSION_RE.fullmatch(spec_version())


def test_pyproject_and_manifest_agree(manifest: Dict[str, Any]) -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]

    assert manifest["spec_version"] == declared
    assert manifest["tag"] == tag_for(declared)


def test_tag_naming() -> None:
    assert tag_for("0.1.0") == "spec-v0.1.0"


# --- the manifest describes what it ships -----------------------------------


def test_manifest_lists_every_suite(manifest: Dict[str, Any]) -> None:
    shipped = {suite["file"] for suite in manifest["test_vectors"]}
    present = {f"test_vectors/{path.name}" for path in (REPO_ROOT / "test_vectors").glob("*.json")}

    assert shipped == present


def test_manifest_lists_every_proto(manifest: Dict[str, Any]) -> None:
    shipped = {entry["file"] for entry in manifest["proto"]}
    present = {f"proto/{path.name}" for path in (REPO_ROOT / "proto").glob("*.proto")}

    assert shipped == present


def test_manifest_suites_carry_cases_and_provenance(manifest: Dict[str, Any]) -> None:
    for suite in manifest["test_vectors"]:
        assert suite["cases"] > 0, f"{suite['file']} ships no cases"
        assert suite["source"] in {"charon", "spec"}
        assert suite["charon_ref"]


def test_unreleased_behaviours_say_what_to_do_instead(anchor: Anchor) -> None:
    # An implementation on a released Charon will not see these on the wire. An
    # entry with no note tells the reader a problem exists and nothing more.
    for behaviour in anchor.behaviours:
        if not behaviour.released:
            assert behaviour.note, f"unreleased behaviour {behaviour.name!r} carries no note"


def test_released_behaviours_carry_a_comparable_version(manifest: Dict[str, Any]) -> None:
    for behaviour in manifest["compatibility"]["behaviours"]:
        triple = behaviour["first_charon_release_semver"]
        if behaviour["first_charon_release"] is None:
            assert triple is None
            continue

        assert triple is not None and len(triple) == 3
        assert behaviour["first_charon_release"] == "v{}.{}.{}".format(*triple)


def test_release_ordering_is_not_lexical(anchor: Anchor) -> None:
    # The reason the triple is shipped at all: a consumer comparing tag strings
    # concludes v1.11.0 behaviour is present on a v1.9.0 Charon.
    releases: Dict[str, tuple[int, int, int]] = {}
    for behaviour in anchor.behaviours:
        triple = behaviour.semver
        if triple is not None and behaviour.first_charon_release is not None:
            releases[behaviour.first_charon_release] = triple

    assert {"v1.9.0", "v1.11.0"} <= set(releases), "expected both releases in the table"

    assert "v1.11.0" < "v1.9.0"  # the trap
    assert releases["v1.11.0"] > releases["v1.9.0"]  # the fix


@pytest.mark.parametrize("bad", ["1.9.0", "v1.9", "v1.9.0-rc1", "main", "latest"])
def test_unparsable_release_is_rejected(bad: str) -> None:
    from charon_repo import Behaviour

    behaviour = Behaviour(name="x", first_charon_release=bad, spec="README.md", note="")

    with pytest.raises(CharonRepoError, match="unparsable release"):
        _ = behaviour.semver


def test_behaviour_spec_pages_exist(anchor: Anchor) -> None:
    for behaviour in anchor.behaviours:
        assert (REPO_ROOT / behaviour.spec).exists(), f"{behaviour.name!r} cites {behaviour.spec}"


def test_readme_compatibility_table_matches_the_anchor(anchor: Anchor) -> None:
    # README.md is the human-facing copy of the same table. If they drift, a
    # release ships a manifest that contradicts the page implementers read first.
    readme = README_PATH.read_text().replace("`", "")

    for behaviour in anchor.behaviours:
        rows = [line for line in readme.splitlines() if behaviour.name in line]
        assert rows, f"README.md does not mention behaviour {behaviour.name!r}"

        expected = behaviour.first_charon_release or "unreleased"
        assert any(expected in row for row in rows), (
            f"README.md does not state {expected!r} for {behaviour.name!r}"
        )


# --- the build refuses to mislead -------------------------------------------


def test_build_writes_a_complete_artifact() -> None:
    destination = build(spec_version(), archive=False)

    assert (destination / "manifest.json").exists()
    assert (destination / "test_vectors" / "qbft_hashing.json").exists()
    assert (destination / "proto" / "priority.proto").exists()
    # The prose spec is deliberately not shipped; see docs/versioning.md.
    assert not (destination / "docs").exists()


@pytest.mark.parametrize("version", ["0.1", "v0.1.0", "0.1.0-rc1", "", "1.0.0.0"])
def test_verify_rejects_malformed_versions(manifest: Dict[str, Any], version: str) -> None:
    with pytest.raises(CharonRepoError, match="MAJOR.MINOR.PATCH"):
        verify(manifest, version)


def test_verify_rejects_an_empty_artifact(manifest: Dict[str, Any]) -> None:
    empty = copy.deepcopy(manifest)
    empty["test_vectors"] = []

    with pytest.raises(CharonRepoError, match="would be empty"):
        verify(empty, "0.1.0")


def test_verify_rejects_a_suite_with_no_cases(manifest: Dict[str, Any]) -> None:
    broken = copy.deepcopy(manifest)
    broken["test_vectors"][0]["cases"] = 0

    with pytest.raises(CharonRepoError, match="no cases"):
        verify(broken, "0.1.0")


def test_verify_rejects_a_behaviour_citing_a_missing_page(manifest: Dict[str, Any]) -> None:
    broken = copy.deepcopy(manifest)
    broken["compatibility"]["behaviours"][0]["spec"] = "docs/dv-spec/does-not-exist.md"

    with pytest.raises(CharonRepoError, match="missing"):
        verify(broken, "0.1.0")


def test_verify_rejects_a_missing_proto(manifest: Dict[str, Any]) -> None:
    broken = copy.deepcopy(manifest)
    broken["proto"][0]["file"] = "proto/does-not-exist.proto"

    with pytest.raises(CharonRepoError, match="missing proto"):
        verify(broken, "0.1.0")
