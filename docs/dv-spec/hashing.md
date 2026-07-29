# Canonical Encoding and Hashing

Every hash a Distributed Validator signs or compares on the wire is taken over
protobuf bytes. Protobuf does not define a canonical encoding, so two
implementations that serialise the same message differently compute different
hashes: signatures fail to verify, `value_hash` comparisons miss, and priority
topics fall into separate groups. Nothing about this failure mode is visible in a
message dump — the messages look identical.

This page pins the encoding and the hash down exactly. It corresponds to
Charon's `hashProto`, which appears identically in `core/consensus/qbft` and
`core/priority`.

Cluster configuration files are hashed differently — by walking the object's
fields through a full SSZ hasher, with explicit list capacities and length
mixins. That construction shares only its tree shape with the one below, and is
specified in [Cluster Files](cluster-files.md#ssz-hashing-rules).

## Deterministic protobuf encoding

Charon marshals with Go's `proto.MarshalOptions{Deterministic: true}`. Three
rules make that canonical:

1. Fields are emitted in ascending field-number order.
2. Map entries are emitted in ascending key order.
3. A singular scalar field equal to its zero value is omitted entirely. A map
   entry's key and value are **not** — map entries have explicit presence, so a
   zero key or empty value is still emitted as a zero-length record.

Rule 3 is the one implementations get wrong. Three consequences worth stating
separately:

- An `UnsignedDataSet` entry with an empty value encodes its value field as
  `0x1200`, not as nothing at all.
- A present-but-empty embedded message encodes as a zero-length record. A
  `QBFTMsg` carrying `Duty{slot: 0, type: 0}` emits `0x1200` for field 2, and a
  `Duty` with both fields zero encodes to zero bytes.
- A `oneof` member has explicit presence too. A `google.protobuf.Value` holding
  the empty string emits `0x1a00`.

Reserved field numbers matter as much as present ones. `QBFTMsg` reserves 5, 7,
9 and 10 from fields that have been removed. An implementation that renumbered
the remaining fields to close those gaps would produce a different encoding and a
different signing root.

## Hash root

The hash is an SSZ merkleization of the encoding, split into 32-byte chunks:

1. Right-pad the encoding with zeros to a multiple of 32 bytes.
2. Merkleize the chunks with SHA-256, sizing the tree to the chunk count rounded
   up to a power of two. Complete an odd level with that level's zero-subtree
   hash, not with a zero leaf.

Two properties of this construction are surprising and load-bearing:

- **There is no length mixin.** Encodings differing only in trailing zero bytes
  hash identically. This is safe only because the input is canonical, where
  trailing zeros cannot vary.
- **An encoding of 32 bytes or fewer is not hashed at all.** The result is the
  encoding, zero-padded. `Duty{slot: 1, type: 2}` therefore "hashes" to
  `0x0801100200…00`, and an empty message to 32 zero bytes.

See the Python reference implementation: [`dv_spec.encoding.proto`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/encoding/proto.py) and [`dv_spec.encoding.ssz`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/encoding/ssz.py).

## QBFT signing root

A QBFT message is authenticated by a secp256k1 signature over the hash root of
the message's own encoding with field 8 (`signature`) **excluded** rather than
zeroed. Signing a message and re-deriving the root from the signed message
therefore give the same value, and a receiver recomputes the root the same way.

Both hash fields are always emitted as 32 bytes. "No value" is the zero hash, not
an absent field: a sender that omitted an empty `value_hash` would produce a root
no receiver can reproduce, and its signature would fail to verify. On receive,
Charon treats a 32-byte zero hash and an absent field alike as "no value", but
the signing root is computed over exactly the fields that were sent.

See the Python reference implementation: [`qbft_signing_root`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/consensus/qbft/hashing.py).

## secp256k1 signature form

Every signature made with a node's identity key — QBFT messages, node signatures
over the cluster lock hash, cluster definition operator entries — is 65 bytes laid
out as `R || S || V`, with the recovery id **last**. Charon produces this by
signing with `ecdsa.SignCompact`, which puts the recovery byte first, and then
moving it to the end (`app/k1util`).

- The recovery id is emitted as 0 or 1. On receive Charon also accepts 27 or 28,
  so an implementation that keeps the offset form interoperates.
- The nonce is RFC 6979 deterministic: signing the same digest with the same key
  twice gives identical bytes. Signatures are therefore reproducible, which is
  what lets [`test_vectors/secp256k1_signatures.json`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/test_vectors/secp256k1_signatures.json)
  pin exact signature bytes rather than only checking that verification passes.
- The signer's public key is recovered from the signature rather than carried
  beside it, which is what lets a QBFT message identify its sender by peer index
  alone.

See the Python reference implementation: [`dv_spec.crypto.secp256k1`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/crypto/secp256k1.py).

## Test vectors

[`test_vectors/qbft_hashing.json`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/test_vectors/qbft_hashing.json)
carries encodings and hash roots for every rule above, including each edge case
called out on this page. The values were produced by Charon itself rather than by
this spec, so a passing suite means agreement with the reference implementation.
See [`test_vectors/README.md`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/test_vectors/README.md)
for the file format and how to reproduce the values.
