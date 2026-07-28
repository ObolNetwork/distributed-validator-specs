# InfoSync Interoperability Spec

This document describes InfoSync, the mechanism by which a distributed validator cluster agrees on the versions, protocols, and block proposal types its nodes support — and, from that agreement, selects the consensus protocol every node uses.

InfoSync is the only production use of the [Priority protocol](priority.md). It is what lets a cluster complete a rolling upgrade without a coordinated restart: nodes announce what they support, the cluster converges on what threshold nodes support, and behaviour changes at an epoch boundary.

Scope:

- The three topics and what each carries
- The trigger cadence and the duty the exchange runs under
- How a node orders its local priorities before proposing them
- How the agreed result selects the consensus protocol and proposal types

Out of scope: the priority exchange, scoring and consensus (see [Priority](priority.md)), and the mechanics of switching consensus protocol inside a node.

## Terms and Notation

- `n`: number of nodes in the cluster
- `t`: threshold, `ceil(2n/3)` by default
- `SLOTS_PER_EPOCH`: network constant, 32 on mainnet
- Topic: a named grouping of priorities within one priority exchange
- Priority: one entry within a topic, ordered most-preferred first

## Trigger

An InfoSync exchange is triggered in the **last slot of every epoch**, under a duty of type `DutyInfoSync` at that slot:

```
trigger if slot % SLOTS_PER_EPOCH == SLOTS_PER_EPOCH - 1
duty = Duty{slot: slot, type: DutyInfoSync}
```

Running in the last slot means the result is agreed before the epoch it governs begins. The exchange uses a 6-second priority exchange timeout — half a slot — which is long enough for all peers to respond in practice.

InfoSync only runs when the node's consensus component is QBFT. There is no InfoSync (and no priority protocol at all) under leader-cast consensus.

## Topics

Every exchange carries all three topics. Each is a list of strings ordered most-preferred first.

| Topic      | Carries                                       | Effect of the agreed result                    |
| ---------- | --------------------------------------------- | ---------------------------------------------- |
| `version`  | Supported Charon minor versions               | Advisory: recorded and logged for upgrade visibility |
| `protocol` | Supported libp2p protocol IDs                 | Selects the cluster-wide consensus protocol     |
| `proposal` | Supported block proposal types                | Selects which proposal types may be used        |

The `protocol` topic carries **every** protocol the node supports — consensus, parsigex, peerinfo and priority alike — not just consensus protocols. Consensus selection therefore filters the agreed list by the `/charon/consensus/` prefix.

The `proposal` topic values are `full`, `builder` and `synthetic`. These strings are on the wire and must not be changed.

A node records an agreed result only if the `version` topic produced priorities, which distinguishes a real agreement from an empty one.

## Local Priority Ordering

Before proposing, a node orders its own priorities. This ordering is what the cluster scores, so it is normative.

**Proposal types**, in order: `builder` if the builder API is enabled, then `synthetic` if synthetic proposals are enabled, then always `full`. `full` is unconditionally supported and always last, so a cluster whose nodes enable different features still agrees on something.

**Protocols**: start from the implementation-defined base order, then apply two bumps by protocol *name*, so all versions of the named protocol move to the front together with their relative order preserved:

1. The cluster lock's preferred consensus protocol, if set.
2. The node's own configured consensus protocol, if set.

The order of application matters: configuration is applied second, so it ends up in front. An operator's explicit choice outranks the cluster lock's.

**Versions**: the supported minor versions of the implementation, most recent first.

## Result Selection

The agreed result is a per-topic list of priorities in agreed order. Each node retains a history of agreed results, keyed by the slot of the InfoSync duty that produced them, and up to `MAX_RESULTS = 100` entries.

Lookups are **by slot, not by recency**: the result that governs a slot is the newest retained result whose slot is not after it. A duty is therefore always processed under the agreement that was in force for it, even if a newer agreement has since arrived.

**Consensus protocol.** On each agreed result, the first entry of the `protocol` topic under the `/charon/consensus/` prefix becomes the cluster-wide consensus protocol, and the node switches to it. An agreed list containing no consensus protocol falls back to `/charon/consensus/qbft/2.0.0` rather than failing, which keeps a cluster running through a malformed agreement.

`/charon/consensus/qbft/2.0.0` is currently the only implemented consensus protocol, so in practice the selection is a no-op today. The machinery exists so that a future protocol can be rolled out incrementally.

**Proposal types.** Resolved from the `proposal` topic of the result governing the slot. Before any agreement exists, only `full` is used: a node must not assume its peers support builder or synthetic proposals until they have said so.

**Protocols.** Resolved from the `protocol` topic of the result governing the slot, falling back to the node's own local protocol list before the first agreement.

See the Python reference implementation: [`dv_spec.subspecs.infosync`](../../src/dv_spec/subspecs/infosync/infosync.py).

## Interop Notes

- **Cadence must match**: a node that triggers on a different slot proposes under a duty no peer is exchanging for, and its message is dropped. Both the last-slot-of-epoch rule and the `DutyInfoSync` type must match exactly.
- **The `protocol` topic is not consensus-only**: an implementation that proposes only its consensus protocol IDs scores differently from Charon and can shift the agreed order.
- **Ordering is the input to scoring**: the priority protocol scores by peer count first and position second, so getting the local ordering rules wrong changes the cluster-wide result even when every node supports the same set.
- **Fallbacks are asymmetric**: with no agreement, protocols fall back to the node's *local* list, while proposal types fall back to `full` only. Do not unify them.
- **Slot-keyed lookup**: resolving by "most recent agreement" instead of "newest agreement at or before this slot" produces divergence during the slot in which a new agreement lands.
