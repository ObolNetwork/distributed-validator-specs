"""Check this repo's `proto/` against Charon's protobuf schema at the anchor.

`proto/` is the spec's normative wire schema: an implementer reads it to learn
which field number carries what. Nothing in this repo executes it, though — the
encoders in `src/dv_spec/encoding/` are hand-written with explicit field numbers
— so a divergence between `proto/` and Charon is invisible to every other test
here, and it is fatal for whoever trusts the file. `PriorityMsg` is signed over
its encoding, so swapping two field numbers means no signature ever verifies.

This compares against the *anchor* commit rather than Charon `main`, so the
result is deterministic: it changes only when this repo changes, which is what
makes it safe to run on a pull request. Charon moving is
`check_charon_drift.py`'s job.

The comparison is field-by-field rather than a `buf breaking` diff. `buf`
compares two revisions of one schema, but `proto/` is deliberately a *subset* of
Charon's with different file paths and no `go_package`, so every legitimate
omission would report as a breaking change. Here, omissions are declared per
file in `charon_anchor.json` with a reason, and anything undeclared is a finding.

Usage:
    uv run python scripts/check_proto_parity.py
    uv run python scripts/check_proto_parity.py --repo-path ~/charon

Exits 0 when the schemas agree, 1 when they do not, and 2 when the check itself
could not run.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from charon_repo import (
    EXIT_ERROR,
    EXIT_FOUND,
    EXIT_OK,
    REPO_ROOT,
    Anchor,
    CharonRepoError,
    ProtoPair,
    read_file_at,
    resolve_repo,
)

PROTO_DIR = REPO_ROOT / "proto"

SCALAR_TYPES = frozenset(
    {
        "double",
        "float",
        "int32",
        "int64",
        "uint32",
        "uint64",
        "sint32",
        "sint64",
        "fixed32",
        "fixed64",
        "sfixed32",
        "sfixed64",
        "bool",
        "string",
        "bytes",
    }
)

WELL_KNOWN_PREFIX = "google.protobuf."

FIELD_RE = re.compile(
    r"^(?:(repeated|optional)\s+)?"  # label
    r"(map\s*<\s*[\w.]+\s*,\s*[\w.]+\s*>|[\w.]+)\s+"  # type, including map<k,v>
    r"(\w+)\s*=\s*(\d+)$"  # name = number
)


class ProtoParseError(RuntimeError):
    """A `.proto` file used a construct this parser does not understand.

    Raised rather than skipped. A parser that quietly ignored a line it could not
    classify would report parity it never checked.
    """


@dataclass(frozen=True)
class ProtoField:
    """One field of a protobuf message."""

    number: int
    name: str
    type: str
    label: str

    def describe(self) -> str:
        """Render the field the way the `.proto` file would."""
        prefix = f"{self.label} " if self.label else ""
        return f"{prefix}{self.type} {self.name} = {self.number}"


@dataclass(frozen=True)
class ProtoMessage:
    """One protobuf message: its fields by number, and its reserved numbers."""

    name: str
    fields: tuple[ProtoField, ...]
    reserved: tuple[int, ...]

    def by_number(self) -> Dict[int, ProtoField]:
        """Index the fields by field number, which is what the wire carries."""
        return {field.number: field for field in self.fields}


@dataclass(frozen=True)
class ProtoSchema:
    """A parsed `.proto` file, reduced to what affects the wire."""

    path: str
    package: str
    imports: tuple[str, ...]
    messages: tuple[ProtoMessage, ...]

    def by_name(self) -> Dict[str, ProtoMessage]:
        """Index the messages by their unqualified names."""
        return {message.name: message for message in self.messages}

    def qualify(self, type_name: str) -> str:
        """Resolve a field type to its fully-qualified name.

        A scalar or map is never package-scoped; a name containing a dot is
        already qualified (or is a well-known type); a bare name resolves against
        this file's package. The package therefore has to match Charon's, since
        it is part of every `Any` type URL.
        """
        if type_name in SCALAR_TYPES or type_name.startswith("map<") or "." in type_name:
            return type_name

        return f"{self.package}.{type_name}" if self.package else type_name

    def type_identity(self, type_name: str) -> str:
        """A field type's name for comparison against the other schema.

        A reference to a message in the *same* file compares by its bare name, so
        that a package divergence is reported once instead of being echoed by
        every field that happens to name a sibling message. Scalars, maps,
        well-known types and cross-file references all compare fully qualified,
        where a package difference is a genuine difference.
        """
        bare = type_name.rpartition(".")[2]
        if bare in self.by_name() and self.qualify(bare) == self.qualify(type_name):
            return bare

        return self.qualify(type_name)


def strip_comments(text: str) -> str:
    """Remove `//` comments, ignoring `//` that appears inside a string literal."""
    if "/*" in text:
        raise ProtoParseError("block comments are not supported")

    stripped = []
    for line in text.splitlines():
        in_quotes = False
        cut = len(line)
        for index, char in enumerate(line):
            if char == '"':
                in_quotes = not in_quotes
            elif char == "/" and not in_quotes and line[index + 1 : index + 2] == "/":
                cut = index
                break
        stripped.append(line[:cut])

    return "\n".join(stripped)


def parse_reserved(path: str, body: str) -> List[int]:
    """Parse a `reserved` statement into the numbers it withdraws."""
    numbers = []
    for part in body.removeprefix("reserved").split(","):
        part = part.strip()
        if not part.isdigit():
            raise ProtoParseError(
                f"{path}: unsupported reserved statement {body!r}; "
                "this parser handles single numbers and comma-separated lists only"
            )
        numbers.append(int(part))

    return numbers


def parse_proto(path: str, text: str) -> ProtoSchema:
    """Parse a `.proto` file, raising on any construct that could hide a divergence."""
    package = ""
    imports: List[str] = []
    messages: List[ProtoMessage] = []

    name: str | None = None
    fields: List[ProtoField] = []
    reserved: List[int] = []

    for raw in strip_comments(text).splitlines():
        line = " ".join(raw.split())
        if not line:
            continue

        if name is None:
            if line.startswith("syntax ") or line.startswith("option "):
                continue
            if line.startswith("package "):
                package = line.removeprefix("package ").removesuffix(";").strip()
            elif line.startswith("import "):
                imports.append(line.removeprefix("import ").removesuffix(";").strip().strip('"'))
            elif line.startswith("message "):
                name = line.removeprefix("message ").removesuffix("{").strip()
                fields, reserved = [], []
            else:
                raise ProtoParseError(f"{path}: unsupported top-level statement {line!r}")
            continue

        if line == "}":
            messages.append(ProtoMessage(name, tuple(fields), tuple(sorted(reserved))))
            name = None
            continue

        for construct in ("message ", "enum ", "oneof "):
            if line.startswith(construct):
                raise ProtoParseError(
                    f"{path}: nested {construct.strip()} in {name} is not supported"
                )

        if not line.endswith(";"):
            raise ProtoParseError(f"{path}: unterminated statement in {name}: {line!r}")

        body = line.removesuffix(";").strip()
        if body.startswith("reserved"):
            reserved.extend(parse_reserved(path, body))
            continue

        match = FIELD_RE.match(body)
        if not match:
            raise ProtoParseError(f"{path}: cannot parse field in {name}: {line!r}")

        label, type_name, field_name, number = match.groups()
        field = ProtoField(
            number=int(number),
            name=field_name,
            # `map< string , bytes >` and `map<string,bytes>` are the same type.
            type="".join(type_name.split()),
            label=label or "",
        )
        if any(existing.number == field.number for existing in fields):
            raise ProtoParseError(f"{path}: {name} reuses field number {field.number}")
        if any(existing.name == field.name for existing in fields):
            raise ProtoParseError(f"{path}: {name} reuses field name {field.name!r}")
        if field.number in reserved:
            raise ProtoParseError(f"{path}: {name} uses reserved field number {field.number}")

        fields.append(field)

    if name is not None:
        raise ProtoParseError(f"{path}: message {name} is not closed")

    return ProtoSchema(
        path=path,
        package=package,
        imports=tuple(imports),
        messages=tuple(messages),
    )


def referenced_types(schema: ProtoSchema) -> List[str]:
    """List every non-scalar type the schema's fields refer to, maps unpacked."""
    names = []
    for message in schema.messages:
        for field in message.fields:
            if field.type.startswith("map<"):
                names.extend(field.type.removeprefix("map<").removesuffix(">").split(","))
            else:
                names.append(field.type)

    return [name for name in names if name not in SCALAR_TYPES]


def well_known_import(type_name: str) -> str:
    """The import path a `google.protobuf.*` type requires."""
    return f"google/protobuf/{type_name.removeprefix(WELL_KNOWN_PREFIX).lower()}.proto"


def check_proto_dir_coverage(pairs: Sequence[ProtoPair]) -> List[str]:
    """Report `.proto` files in this repo that no anchor entry claims.

    Without this, adding a spec proto silently opts it out of parity checking.
    """
    mapped = {pair.spec for pair in pairs}
    # rglob, not glob: a proto tucked into a subdirectory must not escape.
    present = {str(path.relative_to(REPO_ROOT)) for path in PROTO_DIR.rglob("*.proto")}

    findings = [
        f"`{path}` is not listed under `protos` in `charon_anchor.json`, so nothing checks it"
        for path in sorted(present - mapped)
    ]
    findings += [
        f"`{path}` is listed in `charon_anchor.json` but does not exist"
        for path in sorted(mapped - present)
    ]
    return findings


def check_spec_consistency(schemas: Sequence[ProtoSchema]) -> List[str]:
    """Report spec protos that would not compile, independent of Charon.

    `proto/` is flat, so its imports cannot match Charon's paths and are not
    compared against them. They still have to be right on their own terms: a
    file that uses `google.protobuf.Any` without importing it, or references a
    message from a file it does not import, is broken for anyone who runs
    `protoc` over the directory. Runs offline, so the test suite covers it.
    """
    defined: Dict[str, str] = {}
    for schema in schemas:
        for message in schema.messages:
            defined[schema.qualify(message.name)] = Path(schema.path).name

    findings = []
    for schema in schemas:
        own = Path(schema.path).name
        used_imports = set()

        for type_name in referenced_types(schema):
            if type_name.startswith(WELL_KNOWN_PREFIX):
                required = well_known_import(type_name)
                used_imports.add(required)
                if required not in schema.imports:
                    findings.append(f"`{own}` uses `{type_name}` without importing `{required}`")
                continue

            source = defined.get(schema.qualify(type_name))
            if source is None:
                findings.append(f"`{own}` references `{type_name}`, which no spec proto defines")
            elif source != own:
                used_imports.add(source)
                if source not in schema.imports:
                    findings.append(
                        f"`{own}` references `{type_name}` without importing `{source}`"
                    )

        for unused in sorted(set(schema.imports) - used_imports):
            findings.append(f"`{own}` imports `{unused}` but uses nothing from it")

    # Two fields of the same type raise the same import finding; report it once.
    return list(dict.fromkeys(findings))


def compare_messages(
    ours: ProtoMessage,
    theirs: ProtoMessage,
    spec: ProtoSchema,
    charon: ProtoSchema,
) -> List[str]:
    """Compare one message's reserved numbers and fields between the two schemas.

    The two schemas are passed alongside the messages because a bare field type
    only resolves against its own file's package.
    """
    name = ours.name
    findings = []
    if ours.reserved != theirs.reserved:
        findings.append(
            f"`{name}` reserves {list(ours.reserved)}, Charon reserves {list(theirs.reserved)}"
        )

    our_fields, their_fields = ours.by_number(), theirs.by_number()
    for number in sorted(set(their_fields) - set(our_fields)):
        findings.append(f"`{name}` is missing Charon's `{their_fields[number].describe()}`")
    for number in sorted(set(our_fields) - set(their_fields)):
        findings.append(f"`{name}` defines `{our_fields[number].describe()}`, absent from Charon")

    for number in sorted(set(our_fields) & set(their_fields)):
        ours_field, theirs_field = our_fields[number], their_fields[number]
        if (
            ours_field.name != theirs_field.name
            or ours_field.label != theirs_field.label
            or spec.type_identity(ours_field.type) != charon.type_identity(theirs_field.type)
        ):
            findings.append(
                f"`{name}` field {number} is `{ours_field.describe()}`, "
                f"Charon has `{theirs_field.describe()}`"
            )

    return findings


def compare_schemas(pair: ProtoPair, spec: ProtoSchema, charon: ProtoSchema) -> List[str]:
    """Compare one spec proto against the Charon file it mirrors."""
    findings = []
    if spec.package != charon.package:
        findings.append(
            f"package is `{spec.package or '(none)'}`, Charon declares `{charon.package}` — "
            "the package is part of the `Any` type URL of every message in this file"
        )

    our_messages = spec.by_name()
    their_messages = charon.by_name()
    ours, theirs = set(our_messages), set(their_messages)
    declared = set(pair.not_mirrored)

    for name in sorted(theirs - ours - declared):
        findings.append(
            f"Charon defines `{name}`, which is not mirrored here; "
            "add it, or list it under `not_mirrored` with a reason"
        )
    for name in sorted(ours - theirs):
        findings.append(f"`{name}` is defined here but not by Charon")
    for name in sorted(declared - theirs):
        findings.append(f"`not_mirrored` lists `{name}`, which Charon no longer defines")
    for name in sorted(declared & ours):
        findings.append(f"`{name}` is listed under `not_mirrored` but is defined here")

    for name in sorted(ours & theirs):
        findings += compare_messages(our_messages[name], their_messages[name], spec, charon)

    return findings


def format_report(anchor: Anchor, findings: Dict[str, List[str]], notes: Iterable[str]) -> str:
    """Render the parity report as Markdown, for a terminal or a job summary."""
    lines = [
        "# Proto parity with Charon",
        "",
        f"- Anchor: `{anchor.commit[:8]}` ({anchor.date})",
        f"- Files compared: {len(anchor.protos)}",
        "",
    ]

    total = sum(len(items) for items in findings.values())
    if not total:
        lines.append("Every mirrored message matches Charon field for field.")
    else:
        scopes = sum(1 for items in findings.values() if items)
        lines.append(f"**{total} divergence(s) across {scopes} scope(s).**")

        for scope, items in findings.items():
            if not items:
                continue
            lines += ["", f"## {scope}", ""]
            lines += [f"- {item}" for item in items]

        lines += [
            "",
            "`proto/` is the wire schema implementers read. Fix it to match Charon at",
            "the anchor, or — if Charon is the side that moved — re-validate the affected",
            "spec and advance the anchor as `check_charon_drift.py` describes.",
        ]

    # Printed either way: an omission that stops being deliberate is a finding,
    # and a reader of a clean report should still see what was left out.
    for note in notes:
        lines += ["", f"> Not mirrored: {note}"]

    return "\n".join(lines)


def collect_findings(anchor: Anchor, repo: Path) -> tuple[Dict[str, List[str]], List[str]]:
    """Parse both sides and compare every mapped file pair."""
    findings: Dict[str, List[str]] = {"charon_anchor.json": check_proto_dir_coverage(anchor.protos)}

    schemas = {}
    for pair in anchor.protos:
        path = REPO_ROOT / pair.spec
        if not path.exists():
            # Not a silent skip: check_proto_dir_coverage above has already
            # reported the missing file as a finding, forcing a non-zero exit.
            continue
        schemas[pair.spec] = parse_proto(pair.spec, path.read_text())

    findings["proto/ (self-consistency)"] = check_spec_consistency(list(schemas.values()))

    notes = []
    for pair in anchor.protos:
        spec = schemas.get(pair.spec)
        if spec is None:
            continue

        charon = parse_proto(pair.charon, read_file_at(repo, anchor.commit, pair.charon))
        findings[f"{pair.spec} ↔ {pair.charon}"] = compare_schemas(pair, spec, charon)
        if pair.not_mirrored:
            notes.append(
                f"`{pair.spec}` deliberately omits {', '.join(f'`{n}`' for n in pair.not_mirrored)}"
                f": {pair.why_not_mirrored}"
            )

    return findings, notes


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
        findings, notes = collect_findings(anchor, repo)
    except (CharonRepoError, ProtoParseError) as error:
        print(f"proto parity check could not run: {error}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        for path in stack:
            shutil.rmtree(path, ignore_errors=True)

    report = format_report(anchor, findings, notes)
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    return EXIT_FOUND if any(findings.values()) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
