"""Guard the source links embedded in the documentation.

Doc pages link to the spec's Python modules and `.proto` files by absolute
GitHub URL, because relative paths out of `docs/` resolve when browsing the
repository but 404 on the published site. Absolute URLs are not checked by
`mkdocs build`, so this test does the checking instead: every linked path must
exist in the repository, and no page may reintroduce a relative escape or a
line-number anchor.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = REPO_ROOT / "docs"

SOURCE_URL_PREFIX = "https://github.com/ObolNetwork/distributed-validator-specs/blob/main/"

SOURCE_URL = re.compile(rf"\]\({re.escape(SOURCE_URL_PREFIX)}([^)]+)\)")
RELATIVE_ESCAPE = re.compile(r"\]\(\.\./\.\./")
LINE_ANCHOR = re.compile(rf"\]\({re.escape(SOURCE_URL_PREFIX)}[^)]*#L\d")


def doc_pages() -> List[Path]:
    return sorted(DOCS_ROOT.rglob("*.md"))


def source_links() -> List[Tuple[Path, str]]:
    return [
        (page, target) for page in doc_pages() for target in SOURCE_URL.findall(page.read_text())
    ]


def test_docs_contain_source_links() -> None:
    # Sanity check: the assertions below are vacuous if the pattern stops
    # matching, for example after a repository rename.
    assert len(source_links()) > 20


def test_source_links_point_at_existing_files() -> None:
    missing = [
        f"{page.relative_to(REPO_ROOT)} -> {target}"
        for page, target in source_links()
        if not (REPO_ROOT / target).exists()
    ]
    assert not missing, "doc links to non-existent files: " + ", ".join(missing)


def test_docs_have_no_relative_source_links() -> None:
    offenders = [
        str(page.relative_to(REPO_ROOT))
        for page in doc_pages()
        if RELATIVE_ESCAPE.search(page.read_text())
    ]
    assert not offenders, (
        "relative links out of docs/ 404 on the published site; "
        f"use {SOURCE_URL_PREFIX}: " + ", ".join(offenders)
    )


def test_source_links_have_no_line_anchors() -> None:
    offenders = [
        str(page.relative_to(REPO_ROOT))
        for page in doc_pages()
        if LINE_ANCHOR.search(page.read_text())
    ]
    assert not offenders, "line-anchored links rot silently: " + ", ".join(offenders)
