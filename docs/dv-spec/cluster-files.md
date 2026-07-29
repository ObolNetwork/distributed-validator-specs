# Distributed Validator Cluster Files

This document specifies the file formats used to define and lock distributed validator clusters.

## Overview

Distributed validator clusters use two primary configuration files:

- **cluster-definition.json**: Defines the intended cluster configuration before key generation
- **cluster-lock.json**: Extends the definition with generated threshold BLS key shares

## cluster-definition.json

The cluster definition file defines the intended cluster configuration before keys have been created in a DKG ceremony. It is created by a cluster coordinator or DV Launchpad and serves as an input to the DKG process.

**Schema:**

```json
{
  "name": "DV cluster", // Optional cosmetic identifier
  "uuid": "AB20D0A2-371C-47D2-9568-2DBF04F3DD13", // Random unique identifier
  "creator": {
    "address": "0x0000000000000000000000001234567890abcdef", // ETH1 address of the creator
    "config_signature": "0x0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef" // EIP712 Signature of config_hash
  },
  "version": "v1.10.0", // Schema version
  "num_validators": 1, // Number of distributed validators to create
  "threshold": 3, // Threshold required for signature reconstruction
  "dkg_algorithm": "default", // DKG algorithm for key generation
  "fork_version": "0x01017000", // Chain/Network identifier
  "config_hash": "0x0000000000000000000000000000000000000000000000001234567890abcdef", // Hash of static fields
  "timestamp": "2025-01-01T12:00:00+00:00", // Creation timestamp
  "operators": [
    {
      "address": "0x0000000000000000000000001234567890abcdef", // ETH1 address of operator
      "enr": "enr:-HW4QEp-BLhP30tqTGFbR9n2PdUKWP9qc0zphIRmn8_jpm4BYkgekztXQaPA_znRW8RvNYHo0pUwyPEwUGGeZu26XlKAgmlkgnY0iXNlY3AyNTZrMaEDG4TFVnsSZECZXT7VqroFZdceGDRgSBn_nBf16dXdB48", // Node ENR (Ethereum Node Record)
      "enr_signature": "0x0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef", // EIP712 Signature of ENR
      "config_signature": "0x0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef" // EIP712 Signature of config_hash
    }
  ],
  "definition_hash": "0x0000000000000000000000000000000000000000000000001234567890abcdef", // Final hash of all fields
  "validators": [
    {
      "fee_recipient_address": "0x0000000000000000000000001234567890abcdef", // ETH1 fee_recipient address
      "withdrawal_address": "0x0000000000000000000000001234567890abcdef" // ETH1 withdrawal address
    }
  ],
  "deposit_amounts": [
    "32000000000" // Partial deposit amounts in gwei
  ],
  "consensus_protocol": "qbft",
  "target_gas_limit": 36000000,
  "compounding": true
}
```

**Key Fields:**

- `operators`: Array of operators participating in the cluster, identified by ETH1 address and ENR
- `num_validators`: Specifies how many distributed validators will be created
- `threshold`: Minimum number of nodes required for signature reconstruction (typically ⌈2n/3⌉)
- `fork_version`: Network identifier (e.g., mainnet: `0x00000000`, hoodi: `0x10000910`, sepolia: `0x90000069`)
- `definition_hash`: SSZ hash used to confirm no ambiguity between definitions
- `config_hash`: Hash of the static (non-changing) fields
- `deposit_amounts`: List of partial deposit amounts in gwei. Each amount must be at least 1 ETH (1000000000 gwei). Individual deposits are limited to 32 ETH for standard validators or 2048 ETH for compounding validators (those using 0x02 withdrawal credentials per EIP-7251). Charon enforces these limits and validates compounding flag.
- `consensus_protocol`: Consensus protocol name (e.g., "qbft").
- `target_gas_limit`: Target block gas limit for the cluster.
- `compounding`: Boolean flag for compounding rewards (0x02 withdrawal credentials).

## cluster-lock.json

The cluster lock file extends the cluster definition with distributed validator BLS public key shares. It is generated after the DKG ceremony and serves as the runtime configuration.

**Schema:**

```json
{
  "cluster_definition": {...},               // Identical to cluster-definition.json
  "distributed_validators": [
    {
      "distributed_public_key": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef", // DV root pubkey
      "public_shares": [                     // Public share for each operator
        "0x000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef",
        "0x000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef"
      ],
      "partial_deposit_data": [              // Deposit data to activate validator
        {
          "pubkey": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef",
          "withdrawal_credentials": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef",
          "amount": "32000000000",
          "signature": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef",
          "deposit_data_root": "0x000000000000000000000000000000000000000000000000000000123456abcdef"
        }
      ],
      "builder_registration": {
        "message": {
          "fee_recipient": "0x0000000000000000000000000000123456abcdef",
          "gas_limit": 30000000,
          "timestamp": 1696000704,
          "pubkey": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef"
        },
        "signature": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef"
      }
    }
  ],
  "signature_aggregate": "0x000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001234567890abcdef", // BLS aggregate signature of lock_hash
  "lock_hash": "0x0000000000000000000000000000000000000000000000000000123456abcdef",           // Hash of definition + distributed_validators
  "node_signatures": [                         // secp256k1 (65-byte R||S||V) signature of lock_hash by each operator's ENR key
    "0x0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000123456abcdef"
  ]
}
```

**Key Fields:**

- `distributed_validators`: Array containing public data for each DV
- `public_shares`: BLS public key shares per operator, ordered by operator index (array indexed 0-based, where index 0 corresponds to operator 1)
- `partial_deposit_data`: Pre-signed deposit data for each partial deposit from `deposit_amounts` (supports split deposits) for the validator
- `builder_registration`: Pre-signed builder registration for the validator
- `signature_aggregate`: BLS aggregate signature proving all key shares exist
- `lock_hash`: Unique identifier for the cluster lock (hash of definition + validators)
- `node_signatures`: secp256k1 signatures (65-byte R||S||V format) by each operator's ENR private key over the lock_hash

## Additional Persistent Files

### Node Identity Key

- Common filename: `charon-enr-private-key`
- Format: hex-encoded string of serialized secp256k1 private key (64 bytes)
- Purpose: Identity key for p2p networking and signing lock/definition operations
- Storage: Should be kept secret and backed up by each operator

### Validators Key Shares

- Common location: `validator_keys/` directory
- Format: EIP-2335 keystores (encrypted JSON)
- Contents:
  - `keystore-*.json`: Encrypted BLS12-381 private key share for each validator
  - `keystore-*.txt`: Password files for encrypted keystores
- Purpose: Threshold BLS key shares used for validator duties (attestations, proposals, etc.) by validator client
- Storage: Should be kept secret and backed up by each operator
- Note: Each operator holds different key shares

## Cluster Lifecycle and File Flow

```text
DV Launchpad / CLI ─┐
                    ├─► cluster-definition.json ──► DKG Process ─┐
       Creator ─────┘                                            ├─► cluster-lock.json ──► DV Node Runtime
                                         Centralized Key Gen ────┘
```

**Typical Flow:**

1. **Definition Creation**:

   - A cluster coordinator uses a DV Launchpad or CLI tool to create `cluster-definition.json`
   - File contains operator ENRs, validator configurations, and network parameters
   - Creator signs the config_hash with their ETH1 private key

2. **Distribution**:

   - The definition is shared with all operators
   - Each operator verifies the definition matches their expectations

3. **DKG Ceremony** (Distributed Key Generation):

   - All operators run the DKG protocol using the shared definition
   - Generates threshold BLS key shares distributed across operators
   - Produces `cluster-lock.json` with public keys and signatures
   - Alternative: For solo operators, centralized key generation can be used

4. **Verification**:

   - Each operator verifies:
     - `definition_hash` matches the agreed-upon configuration
     - `lock_hash` is correctly computed
     - `signature_aggregate` proves all key shares were generated correctly
     - `node_signatures` attest all operators participated

5. **Runtime**:
   - DV nodes load `cluster-lock.json` and their validator key shares
   - Nodes use the configuration to coordinate validator duties
   - The lock file ensures all nodes operate with identical cluster parameters

## Hash Computation and Signing

This section specifies how to compute hashes and signing data for cluster files. **Field ordering during serialization is critical**. The order specified below must be followed exactly.

The field layouts below are those of **version v1.10.0**, which is this spec's
target. Every version has its own layout, and a hash computed with the wrong one
is simply a different hash: v1.9.0 has no `target_gas_limit` or `compounding`
field, and v1.11.0 turns the operator and creator signatures into lists of 65-byte
signatures to support Safe smart-contract multisigs.

### SSZ Hashing Rules

The three hashes are SSZ hash roots, computed by walking the object's fields into
a buffer of 32-byte chunks and collapsing nested structures back to a single
chunk. The layouts below say which fields are visited; these rules say what each
visit does. Getting any of them wrong produces a plausible-looking hash that no
other implementation agrees with.

- **uint64** is written little-endian in the low 8 bytes of a chunk, the
  remaining 24 zero. **bool** is a chunk whose first byte is `0x01` or `0x00`.
  Charon types several of these fields as signed Go ints and casts with
  `uint64(...)`, so a negative value in a file hashes as its two's-complement
  wrapping there; this spec rejects such a file at validation instead.
- **BytesN** is **left**-padded to N bytes if shorter, then written as below. An
  absent 65-byte signature therefore hashes exactly as an all-zero one, which is
  what lets an unsigned definition and a zero-signature definition agree.
- A byte string of **32 bytes or fewer** occupies one chunk, right-padded. A
  longer one is right-padded to a chunk multiple and **merkleized** into a single
  chunk: a 48-byte public key contributes `sha256(bytes[0:32] || bytes[32:48]
  padded)`, not two chunks.
- **Containers** merkleize their field chunks with the tree sized to the field
  count rounded up to a power of two. An odd level is completed with that level's
  zero-subtree hash, not with a zero leaf.
- **Lists** merkleize with the tree sized to the declared **capacity**, not to the
  elements present, and then mix in the length:
  `root = sha256(tree_root || uint64_le(element_count) padded to 32 bytes)`. The
  mixed-in value is the number of elements present. Without it, a list of two
  empty elements and a list of three would collide.
- A **ByteList[N]** declares its capacity in bytes, but the tree is sized in
  chunks, so the capacity is `ceil(N / 32)` leaves and the mixed-in length is the
  **byte** count of the data present. `ByteList[16]` and `ByteList[32]` both give
  a single-leaf tree, so the same bytes hash identically as `version` or as
  `timestamp`; the declared capacity appears only as the bound on the length.
- A **uint64[256]** declares 256 elements of 8 bytes, which is `ceil(256 × 8 / 32)`
  = 64 leaves. `deposit_amounts` is therefore a depth-6 tree even when it holds
  one element, and an empty one hashes its depth-6 zero subtree with a zero
  length mixed in.
- An **empty list** has no chunks at all: its root is the zero subtree at the
  capacity's depth, or the zero chunk if the capacity is a single leaf.

Two details are quirks of Charon's implementation rather than consequences of the
rules, and both are normative because the hashes depend on them:

- `BuilderRegistration.Message.FeeRecipient` is written without a fixed length, so
  unlike every other address in a cluster file a short value is right-padded
  rather than left-padded.
- Every empty list in a file Charon wrote appears as JSON `null`, because Go
  marshals a nil slice that way. A reader MUST treat `null` and `[]` alike.

See the Python reference implementation:
[`dv_spec.encoding.ssz`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/encoding/ssz.py)
for the hasher, [`dv_spec.cluster.hashing`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/cluster/hashing.py)
for the three walks, and [`dv_spec.cluster`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/cluster/definition.py)
for the data model.

### Definition Hash Computation

There are two hashes computed for a cluster definition:

1. **config_hash**: Hash of static configuration fields (excludes operator ENRs and signatures)
2. **definition_hash**: Hash of all fields including ENRs and signatures

Both hashes use SSZ (Simple Serialize) merkleization.

**Config Hash**:

```ssz
SSZ Merkleize of:
  Field 0: UUID (ByteList[64])
  Field 1: Name (ByteList[256])
  Field 2: Version (ByteList[16])
  Field 3: Timestamp (ByteList[32])
  Field 4: NumValidators (uint64)
  Field 5: Threshold (uint64)
  Field 6: DKGAlgorithm (ByteList[32])
  Field 7: ForkVersion (Bytes4)
  Field 8: Operators (CompositeList[256])
    For each operator:
      Field 0: Address (Bytes20) - parsed from 0x-prefixed hex string
  Field 9: Creator (Composite)
    Field 0: Address (Bytes20) - parsed from 0x-prefixed hex string
  Field 10: ValidatorAddresses (CompositeList[65536])
    For each validator address:
      Field 0: FeeRecipientAddress (Bytes20) - parsed from 0x-prefixed hex
      Field 1: WithdrawalAddress (Bytes20) - parsed from 0x-prefixed hex
  Field 11: DepositAmounts (uint64[256])
  Field 12: ConsensusProtocol (ByteList[256])
  Field 13: TargetGasLimit (uint64)
  Field 14: Compounding (bool)
```

**Definition Hash**:

```ssz
SSZ Merkleize of:
  Field 0: UUID (ByteList[64])
  Field 1: Name (ByteList[256])
  Field 2: Version (ByteList[16])
  Field 3: Timestamp (ByteList[32])
  Field 4: NumValidators (uint64)
  Field 5: Threshold (uint64)
  Field 6: DKGAlgorithm (ByteList[32])
  Field 7: ForkVersion (Bytes4)
  Field 8: Operators (CompositeList[256])
    For each operator:
      Field 0: Address (Bytes20) - parsed from 0x-prefixed hex string
      Field 1: ENR (ByteList[1024]) - encoded as UTF-8 bytes of ENR string
      Field 2: ConfigSignature (Bytes65)
      Field 3: ENRSignature (Bytes65)
  Field 9: Creator (Composite)
    Field 0: Address (Bytes20) - parsed from 0x-prefixed hex string
    Field 1: ConfigSignature (Bytes65)
  Field 10: ValidatorAddresses (CompositeList[65536])
    For each validator address:
      Field 0: FeeRecipientAddress (Bytes20) - parsed from 0x-prefixed hex
      Field 1: WithdrawalAddress (Bytes20) - parsed from 0x-prefixed hex
  Field 11: DepositAmounts (uint64[256])
  Field 12: ConsensusProtocol (ByteList[256])
  Field 13: TargetGasLimit (uint64)
  Field 14: Compounding (bool)
  Field 15: ConfigHash (Bytes32) - the config_hash computed above
```

**Important Notes:**

- Bytes20 fields (addresses): Parse from 0x-prefixed hex string to raw 20 bytes. An empty string decodes to no bytes and is then left-padded to 20 zero bytes, so an absent address hashes as the zero address
- Bytes4 (fork_version): Use raw 4 bytes
- ByteList fields: UTF-8 encode strings, then hash as a byte list of the stated capacity, mixing in the byte length
- CompositeList: merkleize each element to one chunk, then merkleize the list to its declared capacity and mix in the number of elements present
- Ordering: Fields must be hashed in exact numerical order shown above

The `config_hash` excludes operator ENRs and every signature for a reason worth
stating outright: operators sign the config hash, and they sign it at different
times. If the hash moved when a signature or an ENR arrived, every signature
already collected would become invalid. An implementation whose config hash
depends on any of those fields will appear to work until the second operator
signs.

### Lock Hash Computation

The lock hash uniquely identifies a cluster lock file. It is computed as:

```ssz
SSZ Merkleize of:
  Field 0: Definition (Composite) - full definition hash as above
  Field 1: Validators (CompositeList[65536])
    For each DistValidator:
      Field 0: PubKey (Bytes48)
      Field 1: PubShares (CompositeList[256])
        For each pubshare: Bytes48
      Field 2: PartialDepositData (CompositeList[256])
        For each deposit data:
          Field 0: PubKey (Bytes48)
          Field 1: WithdrawalCredentials (Bytes32)
          Field 2: Amount (uint64)
          Field 3: Signature (Bytes96)
      Field 3: BuilderRegistration (Composite)
        Field 0: Message (Composite)
          Field 0: FeeRecipient (raw bytes, right-padded if short — see SSZ Hashing Rules)
          Field 1: GasLimit (uint64)
          Field 2: Timestamp (uint64) - Unix timestamp
          Field 3: PubKey (Bytes48)
        Field 1: Signature (Bytes96)
```

### EIP-712 Signature Computation

The cluster uses EIP-712 typed structured data signatures for creator and operator attestations. This allows users to see what they're signing in wallets like MetaMask.

**EIP-712 Domain:**

```javascript
{
  name: "Obol",
  version: "1",
  chainId: <network_chain_id> // e.g., 1 for mainnet
}
```

#### Creator Config Signature

**Primary Type:** `CreatorConfigHash`

**Type Definition:**

```javascript
{
  CreatorConfigHash: [{ name: "creator_config_hash", type: "string" }];
}
```

**Message:**

```javascript
{
  creator_config_hash: "0x<config_hash_hex>"; // 0x-prefixed hex of config_hash
}
```

**Signature Process:**

1. Compute config_hash as specified above
2. Create EIP-712 typed data with domain and message
3. Compute EIP-712 digest: `keccak256("\x19\x01" || domainSeparator || structHash)`
4. Sign digest with creator's ETH1 private key using secp256k1
5. Encode signature as 65-byte R||S||V format

#### Operator Config Signature

**Primary Type:** `OperatorConfigHash`

**Type Definition:**

```javascript
{
  OperatorConfigHash: [{ name: "operator_config_hash", type: "string" }];
}
```

**Message:**

```javascript
{
  operator_config_hash: "0x<config_hash_hex>";
}
```

Signature process is identical to creator config signature.

#### Operator ENR Signature

**Primary Type:** `ENR`

**Type Definition:**

```javascript
{
  ENR: [{ name: "enr", type: "string" }];
}
```

**Message:**

```javascript
{
  enr: "<operator_enr_string>"; // e.g., "enr:-HW4Q..."
}
```

### Lock Hash Signatures

Two types of signatures attest to the lock hash:

#### 1. BLS Aggregate Signature (signature_aggregate)

**Purpose:** Proves that all threshold key shares were correctly generated and operators possess their shares.

**Creation time:** During the DKG ceremony, immediately after all validators' threshold key shares have been successfully generated and distributed to operators.

**Process:**

1. Compute `lock_hash` SSZ as specified above
2. Each operator signs `lock_hash` with all of their BLS secret shares (one share per validator)
3. All partial signatures are exchanged between operators
4. All partial signatures are aggregated into a single BLS signature using BLS signature aggregation
5. Verification: the aggregate must verify over `lock_hash` against every public share of every validator, in file order

This is a **plain** aggregate, not a threshold aggregate: it is verified against
the concatenated public shares, not against the validators' group public keys.
The two aggregations are different operations over the same curve and are easy to
confuse — see [Signature Aggregation](sigagg.md) for the distinction. There is one
signature per share per validator, so a cluster of 4 operators with 2 validators
aggregates 8 signatures and verifies against 8 public shares.

#### 2. Node Signatures (node_signatures)

**Purpose:** Attestation by each operator that they participated in DKG and accept the lock.

**Creation time:** During the DKG ceremony, immediately AFTER the BLS aggregate signature has been created and verified. This is the final step before the cluster lock file is written to disk. Each operator creates their signature independently using their ENR private key.

**Process:**

1. Compute `lock_hash` SSZ as specified above
2. Each operator signs `lock_hash` with their ENR private key (secp256k1)
3. All operators broadcast and collect each other's signatures
   - This ensures all operators can produce an identical `cluster-lock.json` file
   - The final `node_signatures` array contains one signature per operator
4. Signature format: 65-byte R||S||V format (same as Ethereum transactions)

**Verification:**

- Recover public key from `node_signatures` and `lock_hash`
- Verify recovered public key matches operator's ENR public key

### Verifying a Lock Before Use

A node MUST perform all of the following before running with a lock file. The lock
hash is the only thing binding the configuration the operators signed to the keys
the DKG produced, so a lock that passes some of these checks and not others
attests to a different cluster than the one it describes.

1. Recompute `config_hash`, `definition_hash` and `lock_hash` and compare them
   against the values stored in the file. The signatures only bind the fields the
   hashes cover, so a stored hash that disagrees with the content means the
   signatures attest to something else.
2. Check every validator carries exactly one public share per operator, that no
   two validators share a group public key, and that no validator repeats a
   public share. The repeats cannot be left to step 3: a polynomial can
   legitimately take the same value at two points, so a duplicated share does
   not always break reconstruction.
3. Check the public shares reconstruct the group public key — and check **every**
   share, not just the first quorum. Charon recovers the group key from the first
   `threshold` shares, then re-recovers it once per remaining share, substituting
   that share for one of the first. A single corrupted extra share would otherwise
   go unnoticed until that node's partial signatures started failing in
   production.
4. Verify `signature_aggregate` and every entry of `node_signatures` over the
   recomputed `lock_hash`.

Neither signature set is covered by the lock hash, which spans only the definition
and the validators. Editing any covered field after signing therefore changes the
lock hash and invalidates both signature sets, which is the property that makes
this sequence worth performing.

Charon additionally verifies each pre-generated builder registration — the fee
recipient against the definition and the signature against the group key. Those
signatures are beacon chain domain-separated and are out of scope here.

See the Python reference implementation:
[`dv_spec.cluster.verification`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/cluster/verification.py).
Note that it takes each node's public key as an argument rather than decoding the
operator's ENR, since ENR decoding is out of scope for this spec.

### Test Vectors

[`test_vectors/cluster_hashing.json`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/test_vectors/cluster_hashing.json)
carries config, definition and lock hashes for v1.10.0 files, produced by Charon
rather than by this spec. Each case's `input` is a verbatim Charon cluster file, so
a passing suite means an implementation reads the real file format and agrees on
the hashes.

Two cases are worth reading before the others. `signed_single_operator` is
`unsigned_single_operator` with signatures added and nothing else changed: their
`config_hash` values are identical and their `definition_hash` values differ, which
is the property the config hash exists for. `real_keys_3_of_4` is a lock with a
real 3-of-4 BLS sharing — the same sharing
[`test_vectors/bls_threshold.json`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/test_vectors/bls_threshold.json)
pins — with a real signature aggregate and real node signatures, so the whole
verification sequence above can be run against it.

## Implementation Notes

**Hash Computation**:

- Use SSZ (Simple Serialize) for all hashing operations
- Field ordering must exactly match the version-specific schemas above
- Use SSZ merkleization with appropriate max lengths for lists
- All hash outputs are 32 bytes (SHA256-based)

**Byte Encoding**:

- **Bytes20/Bytes32/Bytes48/Bytes96**: Fixed-length byte arrays
- **ByteList[N]**: Variable-length byte array with maximum length N
- **CompositeList[N]**: List of composite structures with maximum length N
- **Hex strings**: Parse from 0x-prefixed format to raw bytes before hashing

**Signature Formats**:

- BLS signatures: 96 bytes (BLS12-381 G1 compressed)
- secp256k1 signatures: 65 bytes (R || S || V format where V ∈ {0, 1})
- ETH1 addresses: 20 bytes, displayed as 0x-prefixed hex in JSON

**ENR (Ethereum Node Record)**:

- Encoded as base64 string with `enr:-` prefix
- Contains the node's secp256k1 public key and network metadata
- Used for peer discovery and identity verification
- ENR private key is used to sign `node_signatures`

**SSZ Merkleization Details**:

- Use `fastssz` library or equivalent SSZ implementation
- `MerkleizeWithMixin(index, count, maxLength)` for lists
- `Merkleize(index)` for composites
- `PutBytes()`, `PutUint64()`, `PutBool()` for primitive types

**Backwards Compatibility**:

- Clusters cannot migrate yet from old to new lock format, meaning it's up to the implementer to decide if it supports old formats
- Always verify the `version` field before parsing
- Implementers must support all versions they wish to be compatible with
