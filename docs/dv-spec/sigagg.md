# Signature Aggregation Interoperability Spec

This document describes how a distributed validator turns partial signatures from its operators into the single BLS signature that is broadcast to the beacon chain.

Scope:

- Partial signature verification rules
- The threshold condition that triggers aggregation
- Construction of the aggregate signature
- Verification of the resulting group signature

Out of scope: BLS group arithmetic and pairings, Ethereum signing root and domain computation (see [ParSigEx](parsigex.md)), and the internal storage, trimming and metrics of the partial signature database.

## Terms and Notation

- `n`: number of nodes in the cluster
- `t`: signing threshold, `ceil(2n/3)` by default
- `ShareIdx`: 1-based share index of a node, equal to its 0-based peer index plus one
- `pubshare_i`: public key share of the node at `ShareIdx = i`, recorded in the cluster lock
- `r`: order of the BLS12-381 scalar field
- Partial signature: a BLS signature share, 96-byte compressed G2
- Group signature: the aggregate, also 96-byte compressed G2, verifiable under the validator's aggregate public key

## Pipeline

Aggregation sits at the end of the signing path. Nothing here is a distinct wire protocol — the observable behaviour is *which* aggregate a conforming node produces from a given set of partial signatures.

```
validator client ──▶ validatorapi ──┐
                                    ├──▶ parsigdb ──(threshold)──▶ sigagg ──▶ bcast ──▶ beacon node
peers ──▶ parsigex ─────────────────┘
```

1. A node signs locally and stores its own partial signature; storing locally also broadcasts it to peers over [ParSigEx](parsigex.md).
2. Peers' partial signatures arrive over ParSigEx, are verified, and are stored.
3. When the store holds exactly `t` *matching* partial signatures for a validator, it triggers aggregation.
4. The aggregate is verified and handed to the broadcast component.

Every node runs this pipeline independently, so all `n` nodes produce the same group signature and submit it. Duplicate submissions to the beacon node are expected and harmless.

## Partial Signature Verification

Received partial signatures are verified before storage, so invalid ones never count toward the threshold:

1. Look up the validator's public shares from the cluster lock. An unknown validator public key is rejected — "not part of cluster lock".
2. Look up `pubshare_i` for the claimed `ShareIdx`. An index with no public share is rejected — "invalid shareIdx". A partial signature is only meaningful against the public share of the node that produced it, so it is never verified against a different node's key.
3. Compute the signing root for the duty type, per the Ethereum consensus signature rules.
4. Verify `BLS_Verify(pubshare_i, signing_root, signature_i)`.

The claimed `ShareIdx` is not cross-checked against the libp2p identity of the sending peer. Presenting another node's index only produces a signature that fails verification under that node's public share, so the check is redundant.

Verification lives in the ParSigEx receive path, so locally produced partial signatures are stored unverified — a node trusts its own signing. DKG partial signature exchanges bypass it too: the signing roots are not known when the exchanger is constructed, so the exchanger installs a no-op verifier and verifies each partial signature against its public share immediately before aggregating instead.

## Threshold Trigger

The trigger is evaluated after each partial signature is stored, per (duty, validator public key).

**Deduplication.** Each `ShareIdx` gets one slot. Storing the identical signature again is ignored. Storing a *different* signature under the same `ShareIdx` is an error — "mismatching partial signed data" — so a node cannot change its mind after the fact.

**Grouping.** Signatures are grouped by message root, and only a group of matching roots can aggregate. `t` signatures over *different* data must never aggregate: honest nodes legitimately disagree when, for example, a peer proposes different block contents.

**Exact count.** The condition is `len(group) == t`, not `>= t`. Because it is evaluated once per stored signature, aggregation triggers exactly once — on the arrival of the `t`-th matching signature. Later signatures for the same duty are stored but do not trigger a second aggregation.

Since `t = ceil(2n/3)` implies `2t > n`, two disjoint groups can never both reach `t`, so the selection is unambiguous.

**Signature duties.** Duties of type `DutySignature` (used by DKG partial signature exchanges, not by beacon chain duties) carry no message root, so all signatures for the duty form a single group.

See the Python reference implementation: [`select_threshold_matching` and `store_partial_signature`](../../src/dv_spec/subspecs/sigagg/threshold.py).

## Aggregate Construction

The selected partial signatures are keyed by `ShareIdx`. Keying collapses repeated indices, so the count is re-checked afterwards: `t` signatures originating from fewer than `t` distinct nodes do not authorise an aggregate.

The group signature is the Lagrange interpolation of the shares evaluated at zero, where the secret lives:

```
lambda_i = product over j in S, j != i of (0 - j) * (i - j)^-1   (mod r)
sigma    = sum over i in S of lambda_i * sigma_i                 (in G2)
```

where `S` is the set of participating `ShareIdx` values. Two details decide interop:

- The evaluation points are the **1-based** share indices, matching the indices used to split the key during DKG and to key `public_shares` in the cluster lock. Using 0-based peer indices produces a signature that fails verification.
- Arithmetic on the coefficients is modulo `r`, the scalar field order, not the base field order.

As a sanity check that holds for any index set, the coefficients sum to `1 mod r`.

The same interpolation, applied in G1 to the `public_shares` of the cluster lock, must reconstruct the validator's aggregate public key. Lock verification checks exactly this for several threshold-sized subsets, which makes 1-based share indexing normative at cluster load time, before any duty is ever signed.

See the Python reference implementation: [`lagrange_coefficient`, `aggregation_coefficients` and `select_aggregation_inputs`](../../src/dv_spec/subspecs/sigagg/aggregation.py).

### Threshold Aggregation Versus Plain Aggregation

Two different BLS aggregations appear in a cluster's lifetime, and they are not interchangeable:

| Artifact                                              | Aggregation                          | Verified against                                  |
| ----------------------------------------------------- | ------------------------------------ | ------------------------------------------------- |
| Beacon chain duties (attestations, blocks, …)          | Threshold (Lagrange, `t` shares)     | The validator's aggregate public key              |
| DKG deposit data, validator registrations             | Threshold (Lagrange, `t` shares)     | The validator's aggregate public key              |
| DKG cluster lock hash signature                       | Plain aggregation of *all* collected partial signatures | `VerifyAggregate` over the matching list of public shares |

The lock hash signature is a multi-signature, not a reconstructed key: it aggregates every partial signature collected across all validators and is verified against the corresponding list of public shares. Applying threshold interpolation to it produces a signature the lock file verifier rejects.

## Aggregate Verification

The aggregate is verified before being broadcast, using the same Ethereum consensus signature rules as a partial signature but against the validator's aggregate public key rather than a public share. A failure here means the cluster's key material or share indexing is inconsistent, and the duty is failed rather than submitted.

The verified signature is then injected into one of the partial signatures' data to form the complete signed duty object. For attestations, the data carrying a validator index is preferred, because peers omit the validator index and only the local validator client supplies it.

## Interop Notes

- **`ShareIdx` is 1-based** throughout aggregation: in `ParSignedData.share_idx`, in the `public_shares` map of the cluster lock, and as the Lagrange evaluation points. Peer indices are 0-based; the two must not be confused.
- **Signature encoding**: partial and aggregate signatures alike are 96-byte compressed G2 points. Public keys and shares are 48-byte compressed G1 points.
- **Exactly-once trigger**: an implementation that aggregates on `>= t` will aggregate repeatedly as later signatures arrive, and broadcast duplicates that differ from its peers' aggregates.
- **Message roots must match Charon's**: grouping is by root, so any divergence in root computation splits the group and stalls aggregation at the threshold.
