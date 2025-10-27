## Distributed Validator Cluster Files

This document specifies the file formats used to define and lock distributed validator clusters.

### Overview

Distributed validator clusters use two primary configuration files:

- **cluster-definition.json**: Defines the intended cluster configuration before key generation
- **cluster-lock.json**: Extends the definition with generated threshold BLS key shares

### cluster-definition.json

The cluster definition file defines the intended cluster configuration before keys have been created in a DKG ceremony. It is created by a cluster coordinator or DV Launchpad and serves as input to the DKG process.

**Schema:**

```json
{
  "name": "best cluster", // Optional cosmetic identifier
  "uuid": "1234-abcdef-1234-abcdef", // Random unique identifier
  "creator": {
    "address": "0x123..abfc", // ETH1 address of the creator
    "config_signature": "0x123654...abcedf" // EIP712 Signature of config_hash
  },
  "version": "v1.8.0", // Schema version
  "num_validators": 1, // Number of distributed validators to create
  "threshold": 3, // Threshold required for signature reconstruction
  "dkg_algorithm": "default", // DKG algorithm for key generation
  "fork_version": "0x01017000", // Chain/Network identifier
  "config_hash": "0xabcfde...acbfed", // Hash of static fields
  "timestamp": "2025-01-01T12:00:00+00:00", // Creation timestamp
  "operators": [
    {
      "address": "0x123..abfc", // ETH1 address of operator
      "enr": "enr://abcdef...12345", // Node ENR (Ethereum Node Record)
      "enr_signature": "0x123654...abcedf", // EIP712 Signature of ENR
      "config_signature": "0x123456...abcdef" // EIP712 Signature of config_hash
    }
  ],
  "definition_hash": "0xabcdef...abcedef", // Final hash of all fields
  "validators": [
    {
      "fee_recipient_address": "0x123..abfc", // ETH1 fee_recipient address
      "withdrawal_address": "0x123..abfc" // ETH1 withdrawal address
    }
  ],
  "deposit_amounts": [
    "32000000000" // Partial deposit amounts in gwei
  ]
}
```

**Key Fields:**

- `operators`: Array of operators participating in the cluster, identified by ETH1 address and ENR
- `num_validators`: Specifies how many distributed validators will be created
- `threshold`: Minimum number of nodes required for signature reconstruction (typically ⌈2n/3⌉)
- `fork_version`: Network identifier (e.g., mainnet: `0x00000000`, goerli: `0x00001020`, sepolia: `0x90000069`)
- `definition_hash`: Merkle root used to confirm no ambiguity between definitions
- `config_hash`: Hash of the static (non-changing) fields
- `deposit_amounts`: List of partial deposit amounts that must sum to at least 32 ETH

### cluster-lock.json

The cluster lock file extends the cluster definition with distributed validator BLS public key shares. It is generated after the DKG ceremony and serves as the runtime configuration.

**Schema:**

```json
{
  "cluster_definition": {...},               // Identical to cluster-definition.json
  "distributed_validators": [
    {
      "distributed_public_key": "0x123..abfc", // DV root pubkey
      "public_shares": [                     // Public share for each operator
        "0x123..abfc",
        "0x123..abfc"
      ],
      "partial_deposit_data": [              // Deposit data to activate validator
        {
          "pubkey": "0x123..abfc",
          "withdrawal_credentials": "0x123..abfc",
          "amount": "32000000000",
          "signature": "0x123456...abcdef",
          "deposit_data_root": "0x123456...abcdef"
        }
      ],
      "builder_registration": {
        "message": {
          "fee_recipient": "0x123456...abcdef",
          "gas_limit": 30000000,
          "timestamp": 1696000704,
          "pubkey": "0x123456...abcdef"
        },
        "signature": "0x123456...abcdef"
      }
    }
  ],
  "signature_aggregate": "0xabcdef...abcedef", // BLS aggregate signature of lock_hash
  "lock_hash": "0xabcdef...abcedef",           // Hash of definition + distributed_validators
  "node_signatures": [                         // Signature of lock_hash by each operator
    "0x123456...abcdef"
  ]
}
```

**Key Fields:**

- `distributed_validators`: Array containing DV public keys and key shares for each validator
- `public_shares`: One BLS public key share per operator, ordered canonically by operator index
- `partial_deposit_data`: Deposit data for each partial deposit (supports split deposits)
- `builder_registration`: Pre-signed MEV-boost builder registration for the validator
- `signature_aggregate`: BLS aggregate signature proving all key shares exist and attest to the cluster
- `lock_hash`: Unique identifier for the cluster lock (hash of definition + validators)
- `node_signatures`: secp256k1 signatures by each operator's ENR key over the lock_hash (v1.7.0+)

### Additional Persistent Files

**Node Identity Key**

- Common filename: `charon-enr-private-key` or similar
- Format: secp256k1 private key (32 bytes)
- Purpose: Identity key for p2p networking and signing lock/definition operations
- Storage: Should be kept secure and backed up by each operator

**Validator Key Shares**

- Common location: `validator_keys/` directory
- Format: EIP-2335 keystores (encrypted JSON)
- Contents:
  - `keystore-*.json`: Encrypted BLS12-381 private key share for each validator
  - `keystore-*.txt` or similar: Password files for encrypted keystores
- Purpose: Threshold BLS key shares used for validator duties (attestations, proposals, etc.)
- Note: Each operator holds different key shares; no single operator can sign alone

### Version History

The cluster file schemas have evolved to support additional features:

- **v1.0.0**: Initial definition and lock versions
- **v1.1.0**: Added `timestamp` field for human identification
- **v1.2.0**: Refactored to 0x-prefixed hex format (Ethereum standard), removed unused `nonce` field
- **v1.3.0**: Added EIP712 signatures for operators (`config_signature`, `enr_signature`)
- **v1.4.0**: Added `creator` field to track cluster creator
- **v1.5.0**: Support for multiple validator addresses per validator
- **v1.6.0**: Added `builder_registration` for MEV-boost support
- **v1.7.0**: Added `node_signatures` field to lock for operator attestation
- **v1.8.0+**: Added `deposit_amounts` for partial deposits, `target_gas_limit`, and compounding withdrawals support

### Cluster Lifecycle and File Flow

```
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
     - `node_signatures` attest all operators participated (v1.7.0+)

5. **Runtime**:
   - DV nodes load `cluster-lock.json` and their validator key shares
   - Nodes use the configuration to coordinate validator duties
   - The lock file ensures all nodes operate with identical cluster parameters

### Implementation Notes

**Hash Computation**:

- Use SSZ (Simple Serialize) for hashing lock and definition structures
- Field ordering and hash tree structure must be consistent with the version

**Signature Formats**:

- BLS signatures: 96 bytes (BLS12-381)
- secp256k1 signatures: 65 bytes (R || S || V format)
- ETH1 addresses: 20 bytes, 0x-prefixed hex in JSON

**ENR (Ethereum Node Record)**:

- Encoded as base64 string with `enr:` prefix
- Contains the node's secp256k1 public key and network metadata
- Used for peer discovery and identity verification

**Backwards Compatibility**:

- Implementations should support reading older version formats
- When writing, use the latest supported version
- Critical: Always verify the `version` field before parsing
