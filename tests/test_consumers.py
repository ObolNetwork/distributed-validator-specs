"""Guard the consumer suites in `consumers/` against drift from this repo.

The Go code is not compiled here — it compiles inside a Charon checkout — so
nothing else in this repository notices when it goes stale. The failure that
matters is silent: adding a vector suite leaves the Go side unaware of it, and
Charon keeps passing while covering less than it claims.

Charon's own `TestEverySuiteIsCovered` catches the same drift, but only for
whoever runs it in a Charon checkout. These tests catch it here, where the suite
is added.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSUMERS = REPO_ROOT / "consumers"
LOADER = CONSUMERS / "go" / "testutil" / "specvectors" / "specvectors.go"
VECTOR_ROOT = REPO_ROOT / "test_vectors"


@pytest.fixture(scope="module")
def loader_source() -> str:
    return LOADER.read_text()


def covered_suites(source: str) -> set[str]:
    """Parse the suite names out of the Go loader's CoveredSuites map."""
    block = re.search(r"var CoveredSuites = map\[string\]string\{(.*?)\n\}", source, re.DOTALL)
    assert block, "CoveredSuites map not found in the Go loader"

    return set(re.findall(r'"([a-z0-9_]+)":\s*"', block.group(1)))


def test_go_consumer_covers_every_suite(loader_source: str) -> None:
    published = {path.stem for path in VECTOR_ROOT.glob("*.json")}

    assert covered_suites(loader_source) == published


def test_go_consumer_pins_this_spec_version(loader_source: str) -> None:
    # The Go loader refuses to run against a manifest whose version differs, so a
    # stale pin here means the consumer cannot load the release this repo builds.
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]

    pinned = re.search(r'const PinnedSpecVersion = "([^"]+)"', loader_source)
    assert pinned, "PinnedSpecVersion not found in the Go loader"
    assert pinned.group(1) == version


def test_consumers_readme_lists_every_go_file() -> None:
    # The README's file table is how someone knows where each file belongs in
    # Charon's tree; a file missing from it has no documented destination.
    readme = (CONSUMERS / "README.md").read_text()

    for path in sorted((CONSUMERS / "go").rglob("*.go")):
        relative = path.relative_to(CONSUMERS / "go")
        assert str(relative) in readme, f"consumers/README.md does not mention {relative}"


def test_every_go_file_is_placed_under_a_charon_package_path() -> None:
    # The layout mirrors Charon's tree so that placement is a copy. A file at the
    # top level would have no destination.
    for path in sorted((CONSUMERS / "go").rglob("*.go")):
        relative = path.relative_to(CONSUMERS / "go")

        assert len(relative.parts) > 1, f"{relative} is not under a package directory"
        assert relative.parts[0] in {"core", "dkg", "testutil"}, (
            f"{relative} is not under a known Charon top-level directory"
        )
