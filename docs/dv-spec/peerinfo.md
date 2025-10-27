## PeerInfo interoperability spec

This document describes the PeerInfo protocol used for exchanging node metadata and monitoring cluster health in distributed validator networks.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers and exchange patterns
- Verification and compatibility rules
- Metrics and observability

Out of scope: cryptographic signature routines, time synchronization mechanisms, transport reliability;

### Terms and notation

- n: number of participating nodes in the cluster
- RTT: round-trip time for a request-response exchange
- Lock hash: SHA-256 hash of the cluster lock file (ensures identical configuration)
- Clock offset: time difference between local and peer clocks
- Semantic version: version format major.minor.patch (e.g., v1.2.3)

### Protocol identifiers (libp2p)

All messages are sent under protocol ID:

```
/charon/peerinfo/2.0.0
```

### Exchange pattern

PeerInfo supports two usage patterns:

#### 1. Periodic exchange (Charon nodes)

Charon validator nodes use a continuous periodic heartbeat:

1. **Ticker start**: Each node runs a ticker that fires every 60 seconds.

2. **Broadcast phase**: On each tick, the node sends its own `PeerInfo` to all peers (except self) via libp2p streams using `SendReceive`.

3. **Handler response**: Each peer that receives a `PeerInfo` request immediately responds with its own current `PeerInfo`.

4. **Metrics update**: The sender calculates RTT, clock offset, and compatibility for each peer response; updates Prometheus metrics.

All nodes run the same ticker-based exchange independently. This results in each node sending to all others every 60 seconds, and each node receiving from all others approximately every 60 seconds.

#### 2. Ad-hoc requests (Relay nodes)

Relay nodes use one-off `DoOnce` requests to gather peer information on-demand:

1. **Connection monitoring**: Relay tracks active connections and periodically checks connected peers (every 10 seconds).

2. **Ad-hoc request**: For each connected peer, relay sends a single `PeerInfo` request via `DoOnce` function.

3. **Cluster grouping**: Relay uses the returned `lock_hash` to group peers by cluster for bandwidth and connection metrics.

4. **No peer list**: Relays do not have a fixed peer list; they query any peer they have an active connection to.

### Message schemas (protobuf-equivalent)

The following structures are used over the wire. The protobufs used by Charon are available [here](https://github.com/ObolNetwork/charon/tree/main/app/promauto/peerinfo).

- PeerInfo

  - charon_version: string // Semantic version (e.g., "v1.2.3")
  - lock_hash: bytes // Cluster lock file hash
  - git_hash: string // Git commit SHA (7 hexadecimal chars)
  - sent_at: Timestamp // Message send time
  - started_at: Timestamp // Node start time
  - builder_api_enabled: bool // MEV-Boost builder API status
  - nickname: string // Human-friendly identifier (max 32 chars)

### Protocol flow

The following describes the periodic exchange flow used by Charon validator nodes. For ad-hoc relay usage, see the Interop notes section.

#### 1. Ticker

Each node independently runs a ticker that fires every 60 seconds:

```
ticker := time.NewTicker(60 * time.Second)
for now := range ticker.C:
  sendOnce(now)  // send to all peers
```

#### 2. Broadcast to all peers

On each tick, send `PeerInfo` to all peers concurrently:

```
for each peer in peers:
  if peer != self:
    go sendReceive(peer, own_peerinfo)
```

Each send is a goroutine performing `SendReceive` (request-response) to one peer.

#### 3. Handler

The handler runs on all nodes and responds immediately to any incoming `PeerInfo` request:

1. **Ignore request content**: The incoming `PeerInfo` is parsed but content is ignored

2. **Build response**: Construct own `PeerInfo` with current metadata

3. **Send response**: Return own `PeerInfo` via the same stream

#### 4. Response processing

Upon receiving a `PeerInfo` response from a peer:

1. **Validate fields**:

   - Verify timestamps are non-nil
   - Verify git_hash matches regex `^[0-9a-f]{7}$`

2. **Calculate RTT**:

   - RTT = current_time - request_sent_time

3. **Calculate clock offset**:

   - expected_sent_time = current_time - (RTT / 2)
   - clock_offset = peer_sent_at - expected_sent_time
   - Clamp to [-3600, 3600] seconds for metrics

4. **Update metrics**: Publish all peer metadata and calculated values to Prometheus

### Verification

#### Version compatibility

Peers check version compatibility using semantic versioning:

1. **Parse peer version** into major.minor.patch components

2. **Compatibility rules**:
   - Accept peers with newer versions (assume forward compatibility)
   - Accept peers with same minor version
   - Reject peers with different minor versions

Example:

- Running v1.2.3 → Accept v1.2.4, v1.2.5, v1.3.0, v2.0.0
- Running v1.2.3 → Reject v1.1.9, v1.0.0

Incompatible peers are logged and tracked in metrics but not disconnected.

#### Lock hash validation

All peers in a cluster must have the same lock hash:

```
if peer_lock_hash != local_lock_hash:
    log_warning("Mismatching peer lock hash")
    set metric: peer_compatible = 0
```

Lock hash mismatches indicate configuration drift and prevent proper cluster operation.

#### Git hash validation

Git hash must be a 7-character hexadecimal string:

```
if not match(peer_git_hash, "^[0-9a-f]{7}$"):
    log_warning("Invalid peer git hash")
```

This enables tracking the exact software version running on each peer.

#### Builder API consistency

All peers should have consistent builder API configuration:

```
if peer_builder_api_enabled != local_builder_api_enabled:
    log_warning("Mismatching peer builder API status")
```

Mismatched builder API settings may lead to different block proposals across the cluster.

### Metrics

The protocol exposes the following Prometheus metrics:

| Metric                              | Type  | Labels              | Description                                       |
| ----------------------------------- | ----- | ------------------- | ------------------------------------------------- |
| `app_peerinfo_clock_offset_seconds` | Gauge | peer                | Peer clock offset in seconds (clamped to ±1 hour) |
| `app_peerinfo_version`              | Gauge | peer, version       | Peer's charon version                             |
| `app_peerinfo_git_commit`           | Gauge | peer, git_hash      | Peer's git commit hash                            |
| `app_peerinfo_start_time_secs`      | Gauge | peer                | Peer start time (unix seconds)                    |
| `app_peerinfo_index`                | Gauge | peer                | Peer index in cluster definition                  |
| `app_peerinfo_version_support`      | Gauge | peer                | 1 if compatible, 0 if incompatible                |
| `app_peerinfo_builder_api_enabled`  | Gauge | peer                | 1 if enabled, 0 if disabled                       |
| `app_peerinfo_nickname`             | Gauge | peer, peer_nickname | Peer's nickname                                   |

Clock offset values are clamped to the range [-3600, 3600] seconds. Extreme values indicate severe time synchronization issues.

### Properties

- **All-to-all exchange**: Every node sends to every other node every 60 seconds
- **Concurrent sends**: Each node sends to all peers concurrently (one goroutine per peer)
- **Best-effort delivery**: Uses libp2p streams with 5-second timeout
- **No retries**: Failed requests wait for next periodic tick
- **Idempotent**: Receiving duplicate responses is harmless
- **No authentication needed**: libp2p peer identity provides authentication

### Interop notes

- **Protocol versioning**: The protocol ID `/charon/peerinfo/2.0.0` identifies the version; future versions may use different IDs
- **Timestamp encoding**: Timestamps use protobuf Timestamp (seconds + nanoseconds since Unix epoch)
- **Git hash format**: Must be lowercase hexadecimal, exactly 7 characters
- **Nickname constraints**: Maximum 32 characters; changes are logged
- **Clock offset calculation**: RTT-based estimation using `peer_sent_at - (now - RTT/2)`
- **Metric clamping**: Clock offsets clamped to ±1 hour to prevent unbounded metric values
- **Log filtering**: Repeated warnings for the same peer are filtered to reduce log noise

#### Relay usage pattern

Relays use the peerinfo protocol differently from validator nodes:

- **Function**: `DoOnce(ctx, p2pNode, peerID)` - single request-response, returns `(PeerInfo, RTT, ok, error)`
- **Trigger**: Connection events and periodic monitoring (every 10 seconds) rather than fixed 60-second ticker
- **Purpose**: Group connected peers by `lock_hash` for bandwidth and connection metrics
- **No validation**: Relays do not check version compatibility, lock hash matches, or clock offsets
- **Metrics**: Track bandwidth (TX/RX), active connections, and new connections per cluster hash
- **Unknown clusters**: Peers that don't support peerinfo protocol are grouped under "unknown" cluster hash
- **No peer list**: Relays query any peer they have an active connection to, not a predefined cluster peer list
- **Half RTT metric**: Relays report `rtt/2` as ping latency metric (single direction approximation)
