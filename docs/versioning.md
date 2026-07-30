# Versioning and releases

This specification is released under its **own** version, not Charon's, and each
release carries a manifest saying which Charon it was validated against.

## Why not Charon's version numbers

The obvious scheme — `spec-v1.11` describes Charon `v1.11.x` — asserts something
this spec cannot honour. The spec tracks Charon `main`, so at any moment it may
specify behaviour that no tagged Charon release carries. At the `6054bcb2` anchor,
three such behaviours exist: the slash-prefixed priority protocol ID, the stable
sort of scored priorities, and sender-bound share indices in the DKG lock-hash
exchange. A release named after a Charon version would claim to describe a Charon
that behaves differently.

The spec is also not a one-to-one restatement of a Charon release. It is a
description of the protocol plus a record of when each behaviour appeared, which
is what an implementation pinned to an older Charon actually needs.

## Version semantics

Releases are `MAJOR.MINOR.PATCH`, tagged `spec-v<version>`.

| Change | Bump |
| ---------------------------------------------------------------------- | ----- |
| Specified wire behaviour changes: a new field, a new rule, a new limit  | MINOR |
| The Charon anchor advances over wire-visible changes                    | MINOR |
| A specified behaviour is **corrected** — the old text was wrong         | MINOR |
| New test vectors or proto comments covering existing behaviour          | PATCH |
| Prose, structure or tooling only                                        | PATCH |
| An implementation conforming to the previous release now fails to interoperate | MAJOR |

A correction bumps MINOR rather than PATCH deliberately. When the spec said
`peer_id` was field 2 of `PriorityMsg` and Charon numbered it 3, an implementation
that had followed the spec had to change its wire output. That the spec calls it a
fix does not make it compatible.

`0.x` means no second implementation has yet passed every vector suite. The first
`1.0.0` is that milestone, not a maturity claim about the prose.

## What a release contains

```
spec-v0.1.0/
├── manifest.json
├── proto/          # the wire schema, one file per Charon proto it mirrors
└── test_vectors/   # the conformance suites, one JSON per suite
```

Machine-consumable contracts only. The prose specification is published as
[a website](index.md) and is not in the artifact: a Go or Rust conformance test
cannot assert against Markdown, and shipping it would imply the artifact is the
place to read the spec.

## Using the manifest

`manifest.json` names the Charon commit the release was validated against, and
lists every specified behaviour that postdates Charon `v1.7.1` with the first
Charon release that carried it:

```json
{
  "spec_version": "0.1.0",
  "charon_anchor": { "commit": "6054bcb2...", "date": "2026-07-29" },
  "compatibility": {
    "behaviours": [
      {
        "name": "MsgSync.nickname field (DKG sync)",
        "first_charon_release": "v1.9.0",
        "first_charon_release_semver": [1, 9, 0]
      },
      {
        "name": "Stable sort of scored priorities",
        "first_charon_release": null,
        "first_charon_release_semver": null
      }
    ]
  }
}
```

**Compare using `first_charon_release_semver`, not the tag string.** Charon's tags
do not order lexically: `"v1.11.0" > "v1.9.0"` is false, because `1 < 9` at the
third character. A consumer asking "does the Charon I run have this?" with a
string comparison silently concludes that `v1.11.0` behaviour is present on
`v1.9.0`. The triple is shipped so nobody has to rediscover that.

A `first_charon_release` of `null` means the behaviour exists only on Charon
`main`. An implementation interoperating with a released Charon must expect that
behaviour to be **absent** on the other side — which is why every such entry
carries a note on what to do instead. The priority protocol ID is the sharp case:
the preferred spelling is unreleased, so the legacy one must still be served.

Conversely, a behaviour whose `first_charon_release` is newer than the Charon a
peer runs is not a conformance failure of that peer.

## Cutting a release

1. Land the change, with the anchor and vectors updated as needed.
2. Bump `version` in `pyproject.toml`.
3. Push the bump, then tag `spec-v<version>` and publish a GitHub release.

Publishing the release triggers `.github/workflows/release.yml`, which rebuilds
the artifact and attaches it. That workflow **fails if the tag and
`pyproject.toml` disagree**, so the bump has to be committed before the tag —
otherwise a release could ship a manifest naming a different version than the tag
a consumer pinned.

Build the artifact locally with:

```bash
uv run python scripts/build_release.py --archive
```
