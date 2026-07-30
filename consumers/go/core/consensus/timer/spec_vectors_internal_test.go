// Copyright © 2026 Obol Labs Inc. Licensed under the terms of a Business Source License 1.1

package timer

import (
	"testing"
	"time"

	"github.com/jonboulle/clockwork"
	"github.com/stretchr/testify/require"

	"github.com/obolnetwork/charon/core"
	"github.com/obolnetwork/charon/testutil/specvectors"
)

// This file runs the spec's round deadline suite. The deadline is computed inside
// doubleEagerLinearRoundTimer.Timer and its inputs come from unexported helpers,
// so this has to be an in-package test.

type deadlineCase struct {
	Name  string `json:"name"`
	Input struct {
		GenesisTimeNanos  int64  `json:"genesis_time_nanos"`
		SlotDurationNanos int64  `json:"slot_duration_nanos"`
		Slot              uint64 `json:"slot"`
		DutyType          int    `json:"duty_type"`
		Round             int64  `json:"round"`
	} `json:"input"`
	DutyStartDelayNanos int64 `json:"duty_start_delay_nanos"`
	RoundTimeoutNanos   int64 `json:"round_timeout_nanos"`
	DeadlineNanos       int64 `json:"deadline_nanos"`
}

func loadDeadlineCases(t *testing.T) []deadlineCase {
	t.Helper()

	var suite struct {
		Cases []deadlineCase `json:"cases"`
	}
	specvectors.Load(t, "timer_deadlines", &suite)
	require.NotEmpty(t, suite.Cases)

	return suite.Cases
}

// TestSpecRoundDeadlineComponents checks every case against the two functions
// that carry the policy — the duty start delay and the round timeout — and the
// arithmetic Timer performs on them.
//
// Nanoseconds are compared as integers because that is what the protocol needs:
// a 5s slot (Gnosis) gives an attester delay of 1666666666ns, which no float can
// hold alongside a unix timestamp.
func TestSpecRoundDeadlineComponents(t *testing.T) {
	for _, tt := range loadDeadlineCases(t) {
		t.Run(tt.Name, func(t *testing.T) {
			duty := core.Duty{Slot: tt.Input.Slot, Type: core.DutyType(tt.Input.DutyType)}
			slotDuration := time.Duration(tt.Input.SlotDurationNanos)

			delay := getDutyStartDelayWithDuration(duty.Type, slotDuration)
			require.EqualValues(t, tt.DutyStartDelayNanos, delay.Nanoseconds())

			timeout := linearRoundTimeout(tt.Input.Round)
			if proposalTimeoutOptimization(duty, tt.Input.Round) {
				timeout = 1500 * time.Millisecond
			}
			require.EqualValues(t, tt.RoundTimeoutNanos, timeout.Nanoseconds())

			// The same composition Timer applies: slot start, duty delay, timeout.
			genesis := time.Unix(0, tt.Input.GenesisTimeNanos)
			slotStart := genesis.Add(slotDuration * time.Duration(duty.Slot))
			deadline := slotStart.Add(delay).Add(timeout)
			require.EqualValues(t, tt.DeadlineNanos, deadline.UnixNano())
		})
	}
}

// TestSpecRoundDeadlineFires drives the real timer with a fake clock and requires
// it to fire at the vector's deadline and not a nanosecond earlier.
//
// Only a few cases: this asserts the wiring from the components to an actual
// timer, which is the same code path for all 216. Running the whole suite this
// way would trade a lot of wall clock for no extra coverage.
func TestSpecRoundDeadlineFires(t *testing.T) {
	wanted := map[string]bool{
		"attester_slot7231_round1_slotdur12s": true, // mainnet, delay = slot/3
		"attester_slot7231_round2_slotdur5s":  true, // Gnosis, non-divisible third
		"proposer_slot7231_round1_slotdur12s": true, // 1.5s proposal-timeout branch
		"aggregator_slot0_round3_slotdur12s":  true, // delay = 2*slot/3, later round
	}

	found := 0

	for _, tt := range loadDeadlineCases(t) {
		if !wanted[tt.Name] {
			continue
		}

		found++

		t.Run(tt.Name, func(t *testing.T) {
			genesis := time.Unix(0, tt.Input.GenesisTimeNanos)
			clock := clockwork.NewFakeClockAt(genesis)

			timer := NewDoubleEagerLinearRoundTimerWithDutyTimingAndClock(
				core.Duty{Slot: tt.Input.Slot, Type: core.DutyType(tt.Input.DutyType)},
				genesis,
				time.Duration(tt.Input.SlotDurationNanos),
				clock,
			)

			expiry, stop := timer.Timer(tt.Input.Round)
			defer stop()

			deadline := time.Unix(0, tt.DeadlineNanos)
			clock.Advance(deadline.Sub(clock.Now()) - time.Nanosecond)

			select {
			case <-expiry:
				require.Fail(t, "timer fired before the deadline")
			default:
			}

			clock.Advance(time.Nanosecond)

			select {
			case <-expiry:
			case <-time.After(time.Second):
				require.Fail(t, "timer did not fire at the deadline")
			}
		})
	}

	require.Len(t, wanted, found, "a named case is missing from the suite")
}
