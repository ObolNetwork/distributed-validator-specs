// Copyright © 2026 Obol Labs Inc. Licensed under the terms of a Business Source License 1.1

package qbft

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/obolnetwork/charon/testutil/specvectors"
)

// This file replays the spec's decided-rebroadcast sequences. The rate limiter is
// a closure inside Run, so it can only be observed by driving a real instance —
// hence an in-package test reusing this package's msg and noopDef helpers.

// TestSpecDecidedResends requires that post-decision ROUND-CHANGE messages
// trigger at most one DECIDED rebroadcast per source per strictly-increasing
// round, capped per source.
//
// The suite carries a per-event decision list as well as a total; this asserts
// the total. Reading the decision for an individual event would need a flush
// after every send that is itself guaranteed not to rebroadcast, and inserting
// such a message changes the very state being measured. Implementations that can
// observe the limiter directly (rather than through a broadcast channel) should
// assert the per-event list instead — it localises which half of the rule broke.
func TestSpecDecidedResends(t *testing.T) {
	var suite struct {
		Cases []struct {
			Name  string `json:"name"`
			Input struct {
				Nodes        int   `json:"nodes"`
				DecidedRound int64 `json:"decided_round"`
				Events       []struct {
					Source int64 `json:"source"`
					Round  int64 `json:"round"`
				} `json:"events"`
			} `json:"input"`
			Rebroadcast       []bool `json:"rebroadcast"`
			TotalRebroadcasts int    `json:"total_rebroadcasts"`
		} `json:"cases"`
	}
	specvectors.Load(t, "qbft_decided_resends", &suite)
	require.NotEmpty(t, suite.Cases)

	const value = 42

	for _, tt := range suite.Cases {
		t.Run(tt.Name, func(t *testing.T) {
			require.NotEmpty(t, tt.Input.Events)
			require.Len(t, tt.Rebroadcast, len(tt.Input.Events))

			ctx, cancel := context.WithCancel(context.Background())
			t.Cleanup(cancel)

			recv := make(chan Msg[int64, int64, int64])
			broadcasts := make(chan MsgType, 1000)

			def := noopDef
			def.Nodes = tt.Input.Nodes
			def.FIFOLimit = 1000
			def.Decide = func(context.Context, int64, int64, []Msg[int64, int64, int64]) {}

			trans := Transport[int64, int64, int64]{
				Broadcast: func(_ context.Context, typ MsgType, _, _, _, _, _, _ int64,
					_ []Msg[int64, int64, int64],
				) error {
					if typ == MsgDecided {
						broadcasts <- typ
					}

					return nil
				},
				Receive: recv,
			}

			go func() {
				_ = Run(ctx, def, trans, 0, 0, make(chan int64), make(chan int64))
			}()

			// The receive channel is unbuffered, so a send only returns once the
			// instance has finished processing every earlier message. That is what
			// makes the count deterministic.
			send := func(m msg) {
				select {
				case recv <- m:
				case <-time.After(5 * time.Second):
					require.Fail(t, "timeout sending to the qbft instance")
				}
			}

			// A justified DECIDED needs a quorum of COMMITs for the decided round.
			var commits []msg
			for peerIdx := 1; peerIdx < tt.Input.Nodes; peerIdx++ {
				commits = append(commits, msg{
					msgType: MsgCommit,
					peerIdx: int64(peerIdx),
					round:   tt.Input.DecidedRound,
					value:   value,
				})
			}

			send(msg{
				msgType: MsgDecided,
				peerIdx: 1,
				round:   tt.Input.DecidedRound,
				value:   value,
				justify: commits,
			})

			for _, event := range tt.Input.Events {
				send(msg{msgType: MsgRoundChange, peerIdx: event.Source, round: event.Round})
			}

			// Flush with a message that cannot rebroadcast: the decided round is
			// stale for any source that has already been served, and every event
			// round in the suite is at or above it.
			send(msg{
				msgType: MsgRoundChange,
				peerIdx: tt.Input.Events[0].Source,
				round:   tt.Input.DecidedRound,
			})

			require.Len(t, broadcasts, tt.TotalRebroadcasts)
		})
	}
}
