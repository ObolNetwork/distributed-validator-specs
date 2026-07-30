"""Priority protocol identifiers.

Scoring and validation live in `dv_spec.subspecs.priority.scoring`, which
mirrors Charon's `core/priority/calculate.go`.
"""

from __future__ import annotations

PROTOCOL_ID = "/charon/priority/2.0.0"
"""Preferred priority protocol ID."""

LEGACY_PROTOCOL_ID = "charon/priority/2.0.0"
"""The original priority protocol ID, missing its leading "/".

Unlike every other protocol in this spec, priority was registered without a
leading slash — a historical accident in Charon (`core/priority/prioritiser.go`)
that put the bare string on the wire. Charon normalised the ID to `PROTOCOL_ID`
and kept this spelling as an alias so patched and unpatched nodes interoperate.

Both IDs must be served: the wire format is identical under either, and every
Charon release up to and including `v1.11.0-rc1` speaks only this one.
"""

PROTOCOLS = (PROTOCOL_ID, LEGACY_PROTOCOL_ID)
"""Supported priority protocol IDs, in order of precedence.

A dialling node offers every ID in this order, so a peer that supports the
slash-prefixed form negotiates it and one that does not falls back to the legacy
form. A listening node registers a handler for each ID *separately*, as an exact
match. The two IDs share no common prefix, so registering them together under a
common prefix would reduce that prefix to the bare wildcard `"*"`, which libp2p
identify would then advertise to peers in place of either real protocol ID.
"""
