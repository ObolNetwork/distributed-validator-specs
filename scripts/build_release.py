"""Assemble a spec release artifact: the manifest, the vectors and the protos.

A consumer suite (Phase 3.2) pins a spec release rather than a commit of this
repository, so what it pins has to be self-describing. The artifact carries the
machine-consumable contracts and nothing else — the prose specification is
published as a website, and a Go or Rust test cannot load Markdown.

The version is the spec's own, not Charon's. The spec tracks Charon `main`, so at
any time it may specify behaviour that no tagged Charon release has: as of the
`6054bcb2` anchor, three such behaviours exist. A tag named after a Charon
release would therefore assert something false. Instead the manifest names the
Charon anchor commit and lists, per behaviour, the first Charon release that
carried it — so a consumer running a released Charon can tell which parts of the
spec apply to it. See `docs/versioning.md`.

Usage:
    uv run python scripts/build_release.py                 # ./dist/spec-v<version>/
    uv run python scripts/build_release.py --version 0.2.0
    uv run python scripts/build_release.py --archive       # also write the .tar.gz

Exits 0 on success and 2 if the release would be inconsistent.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tarfile
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Sequence

from charon_repo import EXIT_ERROR, EXIT_OK, Anchor, CharonRepoError

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
DIST_ROOT = REPO_ROOT / "dist"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_PREFIX = "spec-v"

# What a consumer suite loads. Deliberately not the docs: those are the human
# specification, published as a site, and no test can assert against them.
PAYLOAD = ("test_vectors", "proto")


def spec_version() -> str:
    """Read the spec version from `pyproject.toml`."""
    with PYPROJECT_PATH.open("rb") as handle:
        version: str = tomllib.load(handle)["project"]["version"]

    return version


def tag_for(version: str) -> str:
    """The git tag naming a given spec version."""
    return f"{TAG_PREFIX}{version}"


def suite_summaries() -> List[Dict[str, Any]]:
    """Describe every vector suite, reading each suite's own provenance.

    Read from the suites rather than restated here, so the manifest cannot claim
    a provenance a suite does not carry.
    """
    summaries = []
    for path in sorted((REPO_ROOT / "test_vectors").glob("*.json")):
        suite = json.loads(path.read_text())
        provenance = suite["provenance"]
        case_groups = {
            key: len(value)
            for key, value in suite.items()
            if isinstance(value, list) and value and isinstance(value[0], dict)
        }
        summaries.append(
            {
                "file": f"test_vectors/{path.name}",
                "suite": suite["suite"],
                "description": suite["description"],
                "source": provenance["source"],
                "charon_ref": provenance["charon_ref"],
                "cases": sum(case_groups.values()),
                "groups": case_groups,
            }
        )

    return summaries


def build_manifest(version: str, anchor: Anchor) -> Dict[str, Any]:
    """Assemble the release manifest."""
    return {
        "spec_version": version,
        "tag": tag_for(version),
        "charon_anchor": {
            "repo": anchor.repo,
            "branch": anchor.branch,
            "commit": anchor.commit,
            "date": anchor.date,
        },
        "compatibility": {
            "note": (
                "The spec tracks Charon main, so it can specify behaviour no tagged "
                "Charon release carries. A behaviour with a null first_charon_release "
                "interoperates only with Charon main. Compare against your Charon "
                "using first_charon_release_semver, the [major, minor, patch] triple: "
                'Charon\'s tags are not ordered by string comparison, so "v1.11.0" '
                'sorts below "v1.9.0".'
            ),
            "behaviours": [
                {
                    "name": behaviour.name,
                    "first_charon_release": behaviour.first_charon_release,
                    # The comparable form. Charon's tags do not sort as strings.
                    "first_charon_release_semver": (
                        list(behaviour.semver) if behaviour.semver else None
                    ),
                    "spec": behaviour.spec,
                    **({"note": behaviour.note} if behaviour.note else {}),
                }
                for behaviour in anchor.behaviours
            ],
        },
        "proto": [
            {"file": pair.spec, "mirrors": pair.charon}
            for pair in sorted(anchor.protos, key=lambda pair: pair.spec)
        ],
        "test_vectors": suite_summaries(),
    }


def verify(manifest: Dict[str, Any], version: str) -> None:
    """Refuse to build a release that would mislead whoever pins it."""
    if not VERSION_RE.fullmatch(version):
        raise CharonRepoError(f"version {version!r} must be MAJOR.MINOR.PATCH")

    if not manifest["test_vectors"]:
        raise CharonRepoError("no vector suites found; the artifact would be empty")

    for suite in manifest["test_vectors"]:
        if not suite["cases"]:
            raise CharonRepoError(f"{suite['file']} has no cases")

    # A behaviour with no spec page is unciteable by whoever hits it.
    for behaviour in manifest["compatibility"]["behaviours"]:
        if not (REPO_ROOT / behaviour["spec"]).exists():
            raise CharonRepoError(
                f"behaviour {behaviour['name']!r} cites missing {behaviour['spec']}"
            )

    for entry in manifest["proto"]:
        if not (REPO_ROOT / entry["file"]).exists():
            raise CharonRepoError(f"manifest lists missing proto {entry['file']}")


def build(version: str, archive: bool) -> Path:
    """Write the release directory, and optionally a tarball beside it."""
    anchor = Anchor.load()
    manifest = build_manifest(version, anchor)
    verify(manifest, version)

    destination = DIST_ROOT / tag_for(version)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name in PAYLOAD:
        shutil.copytree(REPO_ROOT / name, destination / name)

    if archive:
        tarball = DIST_ROOT / f"{tag_for(version)}.tar.gz"
        with tarfile.open(tarball, "w:gz") as handle:
            handle.add(destination, arcname=tag_for(version))
        print(f"wrote {tarball.relative_to(REPO_ROOT)}")

    return destination


def main(argv: Sequence[str] | None = None) -> int:
    """Build the release artifact and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument(
        "--version",
        default=spec_version(),
        help="Spec version to build (default: the version in pyproject.toml)",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Also write a .tar.gz beside the release directory",
    )
    args = parser.parse_args(argv)

    try:
        destination = build(args.version, args.archive)
    except CharonRepoError as error:
        print(f"refusing to build release: {error}", file=sys.stderr)
        return EXIT_ERROR

    manifest = json.loads((destination / "manifest.json").read_text())
    cases = sum(suite["cases"] for suite in manifest["test_vectors"])
    print(
        f"wrote {destination.relative_to(REPO_ROOT)}: "
        f"{len(manifest['test_vectors'])} suites, {cases} cases, "
        f"{len(manifest['proto'])} protos, anchor {manifest['charon_anchor']['commit'][:8]}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
