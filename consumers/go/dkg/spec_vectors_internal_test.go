// Copyright © 2026 Obol Labs Inc. Licensed under the terms of a Business Source License 1.1

package dkg

import (
	"testing"
	"time"

	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/stretchr/testify/require"

	"github.com/obolnetwork/charon/cluster"
	"github.com/obolnetwork/charon/core"
	"github.com/obolnetwork/charon/testutil"
	"github.com/obolnetwork/charon/testutil/specvectors"
)

// This file runs the spec's sender-binding suite, which needs this package's
// unexported verifyPeerShareIdx and newExchanger.

// TestSpecParSigExSenderBinding pins that a peer may only contribute a partial
// signature under the share index the cluster assigned it. The suite's peer map
// gives share index 4 to the *second* peer, which is what a cluster looks like
// after operators with lower indices were removed: an implementation deriving the
// expected index from peer position accepts what Charon rejects and rejects what
// it accepts.
func TestSpecParSigExSenderBinding(t *testing.T) {
	var suite struct {
		Cases []struct {
			Name  string `json:"name"`
			Input struct {
				ShareIdxByPeer map[string]int `json:"share_idx_by_peer"`
				Sender         string         `json:"sender"`
				ShareIdx       int            `json:"share_idx"`
			} `json:"input"`
			Accepted bool   `json:"accepted"`
			Reason   string `json:"reason"`
		} `json:"cases"`
		PeerMap []struct {
			Name  string `json:"name"`
			Input struct {
				Peers          []string       `json:"peers"`
				ShareIdxByPeer map[string]int `json:"share_idx_by_peer"`
				PeerIdx        int            `json:"peer_idx"`
			} `json:"input"`
			Accepted bool   `json:"accepted"`
			Reason   string `json:"reason"`
		} `json:"peer_map"`
	}
	specvectors.Load(t, "parsigex_sender_binding", &suite)
	require.NotEmpty(t, suite.Cases)
	require.NotEmpty(t, suite.PeerMap)

	for _, tt := range suite.Cases {
		t.Run(tt.Name, func(t *testing.T) {
			data := core.NewPartialSignature(testutil.RandomCoreSignature(), tt.Input.ShareIdx)

			err := verifyPeerShareIdx(nodeIdxByPeer(tt.Input.ShareIdxByPeer), peer.ID(tt.Input.Sender), data)
			if tt.Accepted {
				require.NoError(t, err)
				return
			}

			require.Error(t, err)
			switch tt.Reason {
			case "unknown_peer":
				require.ErrorContains(t, err, "unknown peer")
			case "share_idx_mismatch":
				require.ErrorContains(t, err, "share index does not match")
			default:
				require.Failf(t, "unknown rejection reason", "%q", tt.Reason)
			}
		})
	}

	// A peer with no assigned index must be rejected at construction. Left until
	// reception, its partial signatures are dropped as coming from an unknown
	// peer, which never surfaces as a validation error — the exchange just never
	// reaches its threshold and times out.
	for _, tt := range suite.PeerMap {
		t.Run("peer_map/"+tt.Name, func(t *testing.T) {
			host := testutil.CreateHost(t, testutil.AvailableAddr(t))

			peers := make([]peer.ID, 0, len(tt.Input.Peers))
			for _, id := range tt.Input.Peers {
				peers = append(peers, peer.ID(id))
			}

			_, err := newExchanger(host, tt.Input.PeerIdx, peers,
				nodeIdxByPeer(tt.Input.ShareIdxByPeer), []sigType{sigLock}, time.Second)

			if tt.Accepted {
				require.NoError(t, err)
				return
			}

			require.Error(t, err)
			// Charon folds both peer-map defects — a peer absent from the map and
			// one assigned a non-positive index — into this one rule, which is why
			// every rejection in the group carries the same slug.
			require.Equal(t, "missing_share_idx", tt.Reason)
			require.ErrorContains(t, err, "missing valid share index")
		})
	}
}

// nodeIdxByPeer builds the peer map from the suite's share indices. PeerIdx is
// left zero: the binding resolves through the map, and a test that filled in a
// plausible position would obscure exactly the coupling the suite denies.
func nodeIdxByPeer(shareIdxByPeer map[string]int) map[peer.ID]cluster.NodeIdx {
	peerMap := make(map[peer.ID]cluster.NodeIdx, len(shareIdxByPeer))
	for id, shareIdx := range shareIdxByPeer {
		peerMap[peer.ID(id)] = cluster.NodeIdx{ShareIdx: shareIdx}
	}

	return peerMap
}
