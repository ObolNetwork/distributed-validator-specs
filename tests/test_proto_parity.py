"""Guard the proto parity checker and the spec-side half of what it checks.

Comparing against Charon needs the network, so that half runs in CI
(`.github/workflows/proto-parity.yml`) rather than here. Two things can be
pinned offline, and both are the difference between a real check and a green
tick: the parser must refuse anything it does not understand — a parser that
skipped an unrecognised line would report parity it never inspected — and
`proto/` must be internally consistent and fully covered by the anchor mapping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_proto_parity as proto_parity  # noqa: E402
from charon_repo import (  # noqa: E402
    EXIT_ERROR,
    EXIT_FOUND,
    EXIT_OK,
    Anchor,
    CharonRepoError,
    ProtoPair,
)
from check_proto_parity import (  # noqa: E402
    ProtoParseError,
    ProtoSchema,
    check_proto_dir_coverage,
    check_spec_consistency,
    compare_schemas,
    parse_proto,
    strip_comments,
)


@pytest.fixture(scope="module")
def anchor() -> Anchor:
    return Anchor.load()


@pytest.fixture(scope="module")
def spec_schemas(anchor: Anchor) -> list[ProtoSchema]:
    return [parse_proto(pair.spec, (REPO_ROOT / pair.spec).read_text()) for pair in anchor.protos]


# --- the real files ---------------------------------------------------------


def test_every_spec_proto_is_mapped(anchor: Anchor) -> None:
    assert check_proto_dir_coverage(anchor.protos) == []


def test_spec_protos_are_self_consistent(spec_schemas: list[ProtoSchema]) -> None:
    # Missing imports and unresolvable types, which no other test would catch:
    # nothing in this repo compiles `proto/`.
    assert check_spec_consistency(spec_schemas) == []


def test_proto_entries_are_sorted_and_paths_unique(anchor: Anchor) -> None:
    # Sorted so that adding a proto is a one-line diff rather than a reshuffle.
    specs = [pair.spec for pair in anchor.protos]

    assert specs == sorted(specs)


def test_charon_paths_are_unique(anchor: Anchor) -> None:
    charon_paths = [pair.charon for pair in anchor.protos]

    assert len(charon_paths) == len(set(charon_paths))


def test_omissions_carry_a_reason(anchor: Anchor) -> None:
    for pair in anchor.protos:
        if pair.not_mirrored:
            assert pair.why_not_mirrored, f"{pair.spec} omits messages without saying why"
        else:
            assert not pair.why_not_mirrored, f"{pair.spec} explains an omission it does not make"


def test_priority_msg_field_numbers(spec_schemas: list[ProtoSchema]) -> None:
    # Charon orders PriorityMsg duty, topics, peer_id, signature. The spec had
    # peer_id and topics transposed, which is interop-fatal: the message is
    # signed over its encoding, so no signature would have verified.
    priority = next(schema for schema in spec_schemas if schema.path.endswith("priority.proto"))
    fields = priority.by_name()["PriorityMsg"].by_number()

    assert [fields[number].name for number in sorted(fields)] == [
        "duty",
        "topics",
        "peer_id",
        "signature",
    ]


def test_qbft_msg_reserves_the_retired_numbers(spec_schemas: list[ProtoSchema]) -> None:
    consensus = next(schema for schema in spec_schemas if schema.path.endswith("consensus.proto"))

    assert consensus.by_name()["QBFTMsg"].reserved == (5, 7, 9, 10)


# --- the parser -------------------------------------------------------------


def test_parses_fields_labels_maps_and_reserved() -> None:
    schema = parse_proto(
        "t.proto",
        """
        syntax = "proto3";
        package a.b.v1;
        option go_package = "github.com/x/y";
        import "google/protobuf/any.proto";

        message Thing {  // trailing comment
          reserved 4, 5;
          string name = 1;
          repeated bytes blobs = 2;
          optional google.protobuf.Any payload = 3;
          map< string , bytes > tags = 6;
        }
        """,
    )

    assert schema.package == "a.b.v1"
    assert schema.imports == ("google/protobuf/any.proto",)
    thing = schema.by_name()["Thing"]
    assert thing.reserved == (4, 5)
    assert [field.describe() for field in thing.fields] == [
        "string name = 1",
        "repeated bytes blobs = 2",
        "optional google.protobuf.Any payload = 3",
        "map<string,bytes> tags = 6",
    ]


def test_strip_comments_keeps_slashes_inside_string_literals() -> None:
    text = 'option go_package = "github.com/o/c/v1"; // a comment'

    assert strip_comments(text).strip() == 'option go_package = "github.com/o/c/v1";'


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("message A {\n  int64 x = 1;\n  int64 y = 1;\n}", "reuses field number"),
        ("message A {\n  int64 x = 1;\n  int64 x = 2;\n}", "reuses field name"),
        ("message A {\n  reserved 1;\n  int64 x = 1;\n}", "uses reserved field number"),
        ("message A {\n  int64 x = 1;\n", "is not closed"),
        ("message A {\n  enum E { Z = 0; }\n}", "nested enum"),
        ("message A {\n  oneof pick { int64 x = 1; }\n}", "nested oneof"),
        ("message A {\n  message B {\n    int64 x = 1;\n  }\n}", "nested message"),
        ("message A {\n  reserved 2 to 4;\n}", "unsupported reserved statement"),
        ("message A {\n  int64 x = 1\n}", "unterminated statement"),
        ("message A {\n  this is not a field;\n}", "cannot parse field"),
        ("service S {\n}", "unsupported top-level statement"),
        ("/* block */\nmessage A {\n}", "block comments are not supported"),
    ],
)
def test_parser_refuses_what_it_cannot_check(source: str, expected: str) -> None:
    # Each of these would otherwise be silently skipped, and silence here reads
    # as parity.
    with pytest.raises(ProtoParseError, match=expected):
        parse_proto("t.proto", f'syntax = "proto3";\n{source}\n')


# --- the comparison ---------------------------------------------------------


CHARON_SIDE = """
syntax = "proto3";
package core.corepb.v1;
message Msg {
  int64 slot = 1;
  repeated Item items = 2;
}
message Item {
  string name = 1;
}
message Debug {
  string note = 1;
}
"""

# The same schema as a spec proto would carry it: `Debug` is declared omitted.
SPEC_SIDE = CHARON_SIDE.replace("message Debug {\n  string note = 1;\n}\n", "")


def pair(
    not_mirrored: tuple[str, ...] = ("Debug",),
    why_not_mirrored: str = "debug only",
) -> ProtoPair:
    """A mapping entry for the synthetic schemas above."""
    return ProtoPair(
        spec="proto/t.proto",
        charon="core/corepb/v1/t.proto",
        not_mirrored=not_mirrored,
        why_not_mirrored=why_not_mirrored,
    )


@pytest.mark.parametrize(
    ("spec_source", "expected"),
    [
        # A transposed field number: the PriorityMsg bug, in miniature.
        (
            "message Msg {\n  repeated Item items = 1;\n  int64 slot = 2;\n}",
            "field 1 is `repeated Item items = 1`",
        ),
        ("message Msg {\n  int64 slot = 1;\n}", "missing Charon's `repeated Item items = 2`"),
        (
            "message Msg {\n  int64 slot = 1;\n  repeated Item items = 2;\n  bool extra = 3;\n}",
            "absent from Charon",
        ),
        # A renamed field keeps its number, so only the name comparison sees it.
        (
            "message Msg {\n  int64 slot_number = 1;\n  repeated Item items = 2;\n}",
            "Charon has `int64 slot = 1`",
        ),
        # Dropping `repeated` changes the wire, and is easy to miss by eye.
        (
            "message Msg {\n  int64 slot = 1;\n  Item items = 2;\n}",
            "Charon has `repeated Item items = 2`",
        ),
        # A changed scalar type keeps the name and number, so only the type
        # comparison sees it — and sint64 is a zigzag encoding, wire-fatal.
        (
            "message Msg {\n  sint64 slot = 1;\n  repeated Item items = 2;\n}",
            "Charon has `int64 slot = 1`",
        ),
    ],
)
def test_field_divergences_are_reported(spec_source: str, expected: str) -> None:
    source = f'syntax = "proto3";\npackage core.corepb.v1;\n{spec_source}\n'
    spec = parse_proto("proto/t.proto", source + "message Item {\n  string name = 1;\n}\n")
    findings = compare_schemas(pair(), spec, parse_proto("c.proto", CHARON_SIDE))

    assert any(expected in finding for finding in findings), findings


def test_declared_omission_is_accepted_and_undeclared_is_not() -> None:
    spec = parse_proto("proto/t.proto", SPEC_SIDE)
    charon = parse_proto("c.proto", CHARON_SIDE)

    assert compare_schemas(pair(), spec, charon) == []

    findings = compare_schemas(pair(not_mirrored=(), why_not_mirrored=""), spec, charon)
    assert any("Charon defines `Debug`" in finding for finding in findings), findings


def test_omission_of_a_message_the_spec_defines_is_reported() -> None:
    spec = parse_proto("proto/t.proto", CHARON_SIDE)

    findings = compare_schemas(pair(), spec, parse_proto("c.proto", CHARON_SIDE))

    assert findings == ["`Debug` is listed under `not_mirrored` but is defined here"]


def test_stale_omission_is_reported() -> None:
    # Charon deleting a message the spec still lists as omitted leaves dead
    # configuration that reads as a considered decision.
    spec = parse_proto("proto/t.proto", SPEC_SIDE)

    findings = compare_schemas(pair(), spec, parse_proto("c.proto", SPEC_SIDE))

    assert findings == ["`not_mirrored` lists `Debug`, which Charon no longer defines"]


def test_package_divergence_is_reported_once() -> None:
    # A missing package changes every `Any` type URL in the file, but it should
    # not also be echoed by every field that names a sibling message.
    spec = parse_proto("proto/t.proto", SPEC_SIDE.replace("package core.corepb.v1;\n", ""))

    findings = compare_schemas(pair(), spec, parse_proto("c.proto", CHARON_SIDE))

    assert len(findings) == 1
    assert "package is `(none)`" in findings[0]


def test_reserved_divergence_is_reported() -> None:
    # Reserved numbers are wire contract: a spec that stops reserving what
    # Charon reserves licenses reuse of a retired field number.
    spec = parse_proto(
        "proto/t.proto",
        SPEC_SIDE.replace("message Msg {\n", "message Msg {\n  reserved 3;\n"),
    )

    findings = compare_schemas(pair(), spec, parse_proto("c.proto", CHARON_SIDE))

    assert findings == ["`Msg` reserves [3], Charon reserves []"]


def test_message_absent_from_charon_is_reported() -> None:
    spec = parse_proto("proto/t.proto", SPEC_SIDE + "message Invented {\n  bool x = 1;\n}\n")

    findings = compare_schemas(pair(), spec, parse_proto("c.proto", CHARON_SIDE))

    assert findings == ["`Invented` is defined here but not by Charon"]


# --- self-consistency and coverage, on failing inputs -------------------------
#
# The real-file tests above assert these return []; if either regressed to
# always returning [], those tests would stay green while a broken or unmapped
# proto ships silently. Each failure branch needs to fire at least once.


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "message A {\n  google.protobuf.Any x = 1;\n}",
            "uses `google.protobuf.Any` without importing `google/protobuf/any.proto`",
        ),
        (
            "message A {\n  Missing x = 1;\n}",
            "references `Missing`, which no spec proto defines",
        ),
        (
            'import "google/protobuf/any.proto";\nmessage A {\n  bool x = 1;\n}',
            "imports `google/protobuf/any.proto` but uses nothing from it",
        ),
    ],
)
def test_consistency_findings_fire(source: str, expected: str) -> None:
    schema = parse_proto("proto/t.proto", f'syntax = "proto3";\npackage a.v1;\n{source}\n')

    findings = check_spec_consistency([schema])

    assert findings == [f"`t.proto` {expected}"]


def test_cross_file_reference_requires_an_import() -> None:
    shared = 'syntax = "proto3";\npackage a.v1;\n'
    defining = parse_proto("proto/other.proto", shared + "message Other {\n  bool x = 1;\n}\n")
    using = parse_proto("proto/t.proto", shared + "message A {\n  Other o = 1;\n}\n")

    findings = check_spec_consistency([defining, using])

    assert findings == ["`t.proto` references `Other` without importing `other.proto`"]


def test_proto_dir_coverage_reports_both_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proto_dir = tmp_path / "proto"
    (proto_dir / "sub").mkdir(parents=True)
    (proto_dir / "mapped.proto").write_text("")
    (proto_dir / "unmapped.proto").write_text("")
    # In a subdirectory, which must not be a blind spot: the scan is recursive.
    (proto_dir / "sub" / "nested.proto").write_text("")

    monkeypatch.setattr(proto_parity, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(proto_parity, "PROTO_DIR", proto_dir)

    findings = check_proto_dir_coverage(
        (
            ProtoPair(spec="proto/mapped.proto", charon="a", not_mirrored=(), why_not_mirrored=""),
            ProtoPair(spec="proto/gone.proto", charon="b", not_mirrored=(), why_not_mirrored=""),
        )
    )

    assert any("proto/unmapped.proto" in item and "nothing checks it" in item for item in findings)
    assert any("proto/sub/nested.proto" in item for item in findings)
    assert any("proto/gone.proto" in item and "does not exist" in item for item in findings)


def test_main_maps_results_to_the_exit_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    # The exit code is the whole interface with the CI workflow: findings
    # printed but exit 0 is a green check that verified nothing.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(proto_parity, "resolve_repo", lambda anchor, path, stack: Path("."))

    monkeypatch.setattr(proto_parity, "collect_findings", lambda anchor, repo: ({"scope": []}, []))
    assert proto_parity.main([]) == EXIT_OK

    monkeypatch.setattr(
        proto_parity, "collect_findings", lambda anchor, repo: ({"scope": ["diverged"]}, [])
    )
    assert proto_parity.main([]) == EXIT_FOUND

    def unreachable(anchor: Anchor, repo: Path) -> tuple[dict[str, list[str]], list[str]]:
        raise CharonRepoError("network unreachable")

    monkeypatch.setattr(proto_parity, "collect_findings", unreachable)
    assert proto_parity.main([]) == EXIT_ERROR
