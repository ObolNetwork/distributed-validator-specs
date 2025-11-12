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

- Bytes20 fields (addresses): Parse from 0x-prefixed hex string to raw 20 bytes
- Bytes4 (fork_version): Use raw 4 bytes
- ByteList fields: UTF-8 encode strings, then SSZ serialize as variable-length byte list with max length
- CompositeList: SSZ merkleize each composite element, then merkleize the list with mixin for max length
- Ordering: Fields must be hashed in exact numerical order shown above

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
          Field 0: FeeRecipient (Bytes20)
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
5. Verification: Aggregate public key (from all validator public shares) must verify the aggregate signature over `lock_hash`

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
