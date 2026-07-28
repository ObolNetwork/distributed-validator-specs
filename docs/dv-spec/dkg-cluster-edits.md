# Cluster Edit Protocols Interoperability Spec

This document describes the four protocols that edit an existing distributed validator cluster: resharing key material, adding operators, removing operators, and replacing an operator.

All four re-run a DKG over the **same validator public keys**, producing fresh private shares and a new cluster lock. The validators, their public keys, and their on-chain deposits are untouched.

Scope:

- The shared protocol framework and its bootstrap
- The four synchronised steps, and the variant a departing operator runs
- Participant sets and share index assignment per protocol
- Threshold rules
- What the lock update rewrites

Out of scope: Pedersen reshare cryptography (see [Pedersen DKG](dkg-pedersen.md)), keystore encryption, on-disk artifact layout.

## Terms and Notation

- `n`, `t`: node count and threshold of the current cluster
- `n'`, `t'`: node count and threshold of the resulting cluster
- `F = n - t`: fault tolerance of the current cluster
- Departing operator: an operator being removed that still takes part in the ceremony
- Current lock order: the operator order of the cluster lock being edited

## Algorithm

Cluster edits always use **Pedersen** reshare, regardless of the cluster definition's `dkg_algorithm` field. FROST is used only for fresh key generation, because a reshare requires participants to contribute existing shares — an operation the FROST flow does not provide. A cluster created with FROST is edited with Pedersen, and this is not a configuration choice.

## Framework

All four protocols share one bootstrap, executed before any step runs:

1. Load the cluster lock and verify its hashes and signatures (skippable with `--no-verify`).
2. Load private key shares from the validator keys directory, if present. The number of shares MUST equal the number of validators in the lock.
3. Load the ENR private key and derive this node's libp2p peer ID.
4. Determine the participant set — this is the only step that differs per protocol (see below).
5. Reject duplicate peer IDs among participants.
6. Start libp2p networking, keyed on the **current** lock's definition hash.
7. Create the per-protocol components: the partial signature exchanger (`sigLock` only), the reliable broadcast component over the participant set, and the node signature broadcaster.
8. Start the [DKG sync protocol](dkg-sync.md), signing the **current** definition hash. Compatibility is checked by implementation minor version.

Two details are wire-visible and must match:

- The ceremony is identified by the definition hash of the lock being edited, not by any newly computed hash. A node that derives it from the new definition cannot connect.
- The reliable broadcast component covers the **participant** set, so every participant — including departing operators — must take part in each broadcast for it to complete.

## Steps

Every protocol runs exactly **four** steps. Nodes advance their DKG sync step counter between each, so all nodes are at the same step at the same time; the counter is visible in `MsgSync.step`.

| Step | Remaining operator            | Departing operator            |
| ---- | ----------------------------- | ----------------------------- |
| 1    | Pedersen reshare              | Pedersen reshare              |
| 2    | Update lock                   | No-op                         |
| 3    | Update node signatures        | Broadcast sentinel signature  |
| 4    | Write artifacts               | No-op                         |

A departing operator still runs the reshare — the remaining nodes need its contribution to rebuild their shares — and still occupies all four sync steps. It cannot simply fall silent at step 3: the node signature exchange is a reliable broadcast requiring every participant, so it broadcasts the 4-byte sentinel `0xdeadbeef` instead of a signature. Assembling nodes drop sentinel entries. See [FROST DKG](dkg-frost.md#node-signature-exchange) for the exchange itself.

### Step 1 — Reshare

Run a Pedersen reshare over all validators, producing new private shares for the resulting cluster. The reshare is given the current threshold as the old threshold, `t'` as the new threshold, and the sets of added and removed peers.

### Step 2 — Update Lock

Build the new lock from the current one:

- Carry over the definition, then clear `creator` and reduce each operator to its **ENR only**. The cleared fields all carry execution-layer or operator signatures over the previous definition; an edit ceremony has no launchpad interaction or operator wallet in the loop to re-collect them, so carrying them forward would leave stale signatures that fail verification.
- Replace the operator list with the resulting operator set, and set the threshold to `t'`.
- Recompute the definition hashes.
- Carry over the validators unchanged, replacing each one's public shares with those derived from the new key shares.
- Recompute the lock hash.
- Sign the new lock hash with this node's new key share, exchange partial signatures with the other remaining nodes under the `sigLock` type, and aggregate them with **plain BLS aggregation** — not threshold interpolation. Verify the result with `VerifyAggregate` over the corresponding public shares, and store it as `signature_aggregate`. See [Signature Aggregation](sigagg.md#threshold-aggregation-versus-plain-aggregation).

The definition version is not changed by an edit.

### Step 3 — Update Node Signatures

Exchange secp256k1 signatures over the **new** lock hash and store them in the lock, then verify the complete lock — hashes, aggregate signature, and node signatures.

### Step 4 — Write Artifacts

Write the ENR private key, the new key shares, and the new lock to a fresh output directory, and optionally publish the lock.

## Participants and Share Indices

Share indices are read from the current cluster lock: an operator's index is its 1-based position in the current lock order. Participation does not change it.

### Reshare

All operators participate. Nothing about the operator set, threshold, or indices changes; only the private shares are refreshed.

### Add Operators

Existing operators plus the new ones. New operators are **appended**, never interleaved, so every existing operator keeps its share index and the new ones take the next indices in the order requested.

The threshold is unchanged. Raising it is not offered: the pre-existing shares would still reconstruct the key below the new threshold, so a raise would not deliver the security it appears to.

### Remove Operators

By default the remaining operators run the ceremony. An explicit participating set overrides this and is used **verbatim, in the order given**, and MAY include operators being removed. That is how a cluster removes more than `F` operators: departing nodes stay in the ceremony long enough to contribute their shares, then drop out at step 2.

The new threshold defaults to `t' = ceil(2n'/3)`. An override must satisfy:

```
ceil(2n'/3) <= t' < n'
```

An override may therefore only **raise** the threshold. A lower one would let the old, larger-cluster shares reconstruct the key below `t'`; a value of `n'` or above means no quorum could ever form.

**Share index compaction.** Removal is the one case where ceremony indices and new-lock indices differ:

- *During* the ceremony, survivors keep their gapped current-lock indices. Dropping the first of four operators leaves survivors signing as 2, 3 and 4.
- In the *new* lock, indices are compacted to `1..n'` in ascending current-lock order, so those same survivors become 1, 2 and 3.

The compaction is not a choice: the lock stores public shares as an ordered **list**, so an operator's list position determines the index it is read back at. The reshare assigns the survivors' new shares in the same ascending order, so the two agree. Keying the new lock's public shares by the old, gapped indices produces a lock whose shares do not reconstruct the validator public key, and which every node rejects at load time.

### Replace Operator

The replacement takes the departing operator's **position**, inheriting its share index and leaving every other operator's index untouched. This is what makes a replacement a one-for-one swap rather than a removal followed by an addition: `n`, `t` and every other index are unchanged, and there is no compaction.

The departing operator does not take part. The replacement is treated as an added peer and the departing operator as a removed peer within the same reshare.

See the Python reference implementation: [`dv_spec.subspecs.dkg.protocols`](../../src/dv_spec/subspecs/dkg/protocols.py).

## Appending Validators

Adding validators to an existing cluster is also a cluster edit, but it is **not** one of the four protocols above and does not use this framework. It runs the ordinary key generation ceremony — the same six-phase flow and step numbering as a fresh DKG (see [DKG Sync](dkg-sync.md#step-numbering-per-ceremony)) — because new validators need fresh key generation, not a reshare of existing shares.

Consequences that distinguish it from the four edit protocols:

- It uses the cluster definition's configured `dkg_algorithm`, so **FROST by default**.
- All existing operators participate; the operator set and threshold are unchanged.
- Validator indices for the ceremony restart at 0 and cover only the **new** validators. The count of validators generated is the number being appended, not the cluster total.
- Deposit data and validator registrations are generated for the new validators and merged with the existing files.
- If a node lacks access to the existing validator shares, the ceremony can run in an unverified mode; the cluster must then be started with lock verification disabled.

## Interop Notes

- **Four steps, always**: the step count is part of the sync handshake. A node that runs a different number of steps stalls its peers, including a departing node that skips the steps it has no work for.
- **Departing nodes are participants**: they contribute to the reshare and to every reliable broadcast. Treating them as absent breaks broadcast completion for everyone.
- **The old definition hash identifies the ceremony**, not the new one.
- **Ceremony indices are gapped, new-lock indices are compact** — and only for removals. Conflating the two produces either invalid lock-hash partial signatures or an unloadable lock.
- **Threshold overrides only go up**, and only on removal. Add and replace leave the threshold alone.
- **Pedersen, not FROST**, for every edit.
