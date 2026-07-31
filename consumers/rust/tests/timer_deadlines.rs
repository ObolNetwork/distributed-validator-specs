//! Runs the `timer_deadlines` suite against pluto's consensus round timers.
//!
//! Pluto's timers are purely relative to `round`. The stored `Duty` on each
//! timer is read in exactly one place in `crates/consensus/src/timer.rs`:
//! `is_proposer`, used by `proposal_timeout_duration` to pick the round-1
//! proposer override. Nothing reads genesis time, slot duration, or slot
//! number. That splits the vectors' three columns across three tests below:
//!
//! - `round_timeouts_with_proposal_timeout_enabled`: `round_timeout_nanos`
//!   under the feature configuration the vectors assume. See Fix round 1
//!   below for why this alone overstates parity.
//! - `round_timeouts_pluto_default_feature_set`: the same column under
//!   pluto's actual *default* configuration, which pins a real divergence on
//!   `PROPOSER`/round-1 cases (see "Fix round 1").
//! - `round_timeout_is_duty_slot_invariant`: a real, code-level pin for the
//!   `deadline_nanos` ABSENT-OK column -- see that test's doc comment.
//!
//! ## Fix round 1
//!
//! The first version of this suite enabled `Feature::ProposalTimeout` and
//! reported an unqualified PASS on `round_timeout_nanos`. That is true only
//! under a non-default feature configuration and hid a real divergence:
//!
//! - Pluto's `Config::default()` has `min_status: Status::Stable` and
//!   `Feature::ProposalTimeout` is `Status::Alpha`
//!   (`crates/featureset/src/lib.rs`), so it is **disabled by default**;
//!   pluto's own `default_matches_go_implementation` test asserts this is
//!   deliberate charon parity.
//! - Charon at the vectors' anchor (`6054bcb2`) has `ProposalTimeout` at
//!   `statusStable` with a `statusStable` minimum
//!   (`app/featureset/featureset.go`), i.e. **enabled by default** -- it was
//!   promoted from alpha in charon commit `06b6371b` ("promote
//!   proposal_timeout feature flag to stable", #4296), first released in
//!   **v1.9.0**, after pluto's v1.7.1 parity anchor.
//!
//! So a default-configured pluto disagrees with the vectors on every
//! `PROPOSER`/round-1 case (pluto: 1s; vectors: 1.5s), and that disagreement
//! is the same class of gap as the `deadline_nanos` column below: a v1.9.0
//! charon behaviour that postdates pluto's pin. `round_timeouts_pluto_default_feature_set`
//! pins it explicitly instead of letting the enabled-feature test's PASS
//! stand in for it.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use pluto_consensus::timer::{RoundTimer, get_round_timer_func};
use pluto_core::types::{Duty, DutyType, SlotNumber};
use pluto_featureset::{Config, Feature, FeatureSet, Status};
use spec_vectors_pluto::load_suite;
use tokio::time::{Instant, advance};

/// Larger than the largest vector timeout (round 10 => 10s), so a single
/// jump always carries the paused clock past whichever deadline is pending.
const ADVANCE: Duration = Duration::from_secs(15);

fn duty_type_from_name(name: &str) -> DutyType {
    match name {
        "PROPOSER" => DutyType::Proposer,
        "ATTESTER" => DutyType::Attester,
        "RANDAO" => DutyType::Randao,
        "AGGREGATOR" => DutyType::Aggregator,
        "SYNC_MESSAGE" => DutyType::SyncMessage,
        "SYNC_CONTRIBUTION" => DutyType::SyncContribution,
        other => panic!("timer_deadlines: unhandled duty_type_name {other}"),
    }
}

/// Builds the feature set the vectors assume: `EagerDoubleLinear` at its
/// Stable default, plus `ProposalTimeout` explicitly enabled (it is Alpha,
/// hence off, under `Config::default()`), `Linear` left at its Alpha
/// default (off).
fn feature_set_with_proposal_timeout_enabled() -> Arc<FeatureSet> {
    Arc::new(
        FeatureSet::from_config(Config {
            min_status: Status::Stable,
            enabled: vec![Feature::ProposalTimeout],
            disabled: vec![],
        })
        .expect("valid feature config"),
    )
}

/// Awaits `timer.timer(round)` under a paused clock and returns the elapsed
/// time from just before the call to the future's resolved deadline.
///
/// `sleep_until` does not resolve on its own under `start_paused = true`:
/// pluto's own timer tests (`assert_fires_after` in
/// `crates/consensus/src/timer.rs`'s test module) spawn the future, call
/// `tokio::time::advance` past the deadline, then `yield_now` before
/// checking it fired. The future's `Output` is the deadline `Instant`
/// itself (captured by the future before any advancing), so the returned
/// duration is exact regardless of how far past the deadline we advance.
async fn measure_round_timeout(timer: &dyn RoundTimer, round: i64) -> Duration {
    let start = Instant::now();
    let fut = timer.timer(round).expect("timer future");
    let handle = tokio::spawn(fut);
    advance(ADVANCE).await;
    tokio::task::yield_now().await;
    let deadline = handle.await.expect("timer task panicked");
    deadline - start
}

#[tokio::test(start_paused = true)]
async fn round_timeouts_with_proposal_timeout_enabled() {
    let suite = load_suite("timer_deadlines");
    let cases = suite["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 216, "expected 216 timer_deadlines cases");

    // With `Linear` off and `EagerDoubleLinear` on (its Stable default),
    // `get_round_timer_func` selects `EagerDoubleLinearRoundTimer` for every
    // duty type -- confirmed against `get_round_timer_func`'s own branching
    // and its `get_timer_func` unit test in `timer.rs`. This PASS holds
    // *only* under `ProposalTimeout` enabled; see the module doc comment
    // and `round_timeouts_pluto_default_feature_set` below for pluto's
    // actual default behaviour.
    let timer_func = get_round_timer_func(feature_set_with_proposal_timeout_enabled());

    let mut failures = Vec::new();
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let input = &case["input"];
        let slot = input["slot"].as_u64().unwrap();
        let round = input["round"].as_i64().unwrap();
        let duty_type = duty_type_from_name(input["duty_type_name"].as_str().unwrap());
        let want = Duration::from_nanos(case["round_timeout_nanos"].as_u64().unwrap());

        // A fresh timer per case: `EagerDoubleLinearRoundTimer` caches a
        // round's first deadline and doubles it on a second `timer()` call
        // for that same round. Calling `timer_func` once per case (as
        // pluto itself does once per consensus instance) means no case
        // shares that cache with another.
        let duty = Duty::new(SlotNumber::from(slot), duty_type);
        let timer = timer_func(duty);

        let got = measure_round_timeout(timer.as_ref(), round).await;
        if got != want {
            failures.push(format!(
                "timer_deadlines/{name}: round timeout {got:?}, want {want:?} (ProposalTimeout enabled)"
            ));
        }
    }

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[tokio::test(start_paused = true)]
async fn round_timeouts_pluto_default_feature_set() {
    let suite = load_suite("timer_deadlines");
    let cases = suite["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 216, "expected 216 timer_deadlines cases");

    // Pluto's actual default: `FeatureSet::default()`, i.e.
    // `Config::default()` (`min_status: Stable`, nothing explicitly
    // enabled/disabled) -- `ProposalTimeout` stays off. This is the
    // configuration pluto ships with at its v1.7.1 parity anchor.
    let timer_func = get_round_timer_func(Arc::new(FeatureSet::default()));

    // Pinned known-divergence: proposer round-1 timeout under charon
    // v1.7.1 parity (pluto's default) is 1s, not the vectors' 1.5s. See the
    // module doc comment ("Fix round 1") for why -- charon promoted
    // `ProposalTimeout` to enabled-by-default in v1.9.0 (#4296), after
    // pluto's anchor. This must flip loudly (the `assert_eq!` below fails)
    // the moment pluto's default configuration changes in either direction.
    const PINNED_DEFAULT_PROPOSER_ROUND1_TIMEOUT: Duration = Duration::from_secs(1);

    let mut divergent_cases = 0usize;
    let mut failures = Vec::new();
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let input = &case["input"];
        let slot = input["slot"].as_u64().unwrap();
        let round = input["round"].as_i64().unwrap();
        let duty_type_name = input["duty_type_name"].as_str().unwrap();
        let duty_type = duty_type_from_name(duty_type_name);
        let want = Duration::from_nanos(case["round_timeout_nanos"].as_u64().unwrap());

        let duty = Duty::new(SlotNumber::from(slot), duty_type);
        let timer = timer_func(duty);
        let got = measure_round_timeout(timer.as_ref(), round).await;

        let is_pinned_divergence = duty_type_name == "PROPOSER" && round == 1;
        if is_pinned_divergence {
            divergent_cases += 1;
            if got != PINNED_DEFAULT_PROPOSER_ROUND1_TIMEOUT {
                failures.push(format!(
                    "timer_deadlines/{name}: default-config round timeout {got:?}, \
                     want pinned {PINNED_DEFAULT_PROPOSER_ROUND1_TIMEOUT:?} (ProposalTimeout default-disabled)"
                ));
            }
            assert_ne!(
                got, want,
                "timer_deadlines/{name}: expected pluto's default config to diverge from the \
                 vector (which assumes ProposalTimeout enabled), but it matched -- pluto's \
                 default must have changed; update this pin"
            );
        } else if got != want {
            failures.push(format!(
                "timer_deadlines/{name}: round timeout {got:?}, want {want:?} (pluto default config)"
            ));
        }
    }

    // 6 duty types x 3 slots x 4 rounds x 3 slot durations = 216 cases;
    // exactly the PROPOSER/round-1 cases (1 duty type x 3 slots x 3
    // durations = 9) are the pinned divergence.
    assert_eq!(
        divergent_cases, 9,
        "expected exactly 9 PROPOSER/round-1 cases pinning the default-config divergence"
    );

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Real, code-level pin for the `deadline_nanos` ABSENT-OK column.
///
/// The vectors' `deadline_nanos` is genesis- and slot-derived
/// (`deadline_nanos = genesis + slot_duration * slot + duty_start_delay +
/// round_timeout`), a determinism pluto does not implement -- see the
/// module doc comment. That absence is only a real ABSENT-OK pin if it is
/// asserted in code, not just claimed in a comment: this test builds two
/// timers for the same duty type and round, differing only in `slot`, and
/// asserts their measured round timeouts are bit-identical. If
/// `EagerDoubleLinearRoundTimer::with_duty` (or `RoundTimer::timer`) ever
/// grows slot-dependence, this fails loudly -- which is exactly the ladder
/// entry "Deterministic (genesis-derived) eager double linear round
/// deadlines" (`first_charon_release: v1.9.0` > pluto's v1.7.1 anchor)
/// flipping.
///
/// Genesis-invariance is not separately exercised here: `RoundTimer::timer`
/// takes only `round`, and the `Duty` it is built from
/// (`pluto_core::types::Duty`) carries only `slot` and `duty_type` -- there
/// is no genesis-time parameter anywhere in this API for a case to vary, so
/// genesis-invariance is guaranteed by the type signature rather than
/// something a test can exercise.
#[tokio::test(start_paused = true)]
async fn round_timeout_is_duty_slot_invariant() {
    let suite = load_suite("timer_deadlines");
    let cases = suite["cases"].as_array().unwrap();

    // Every (duty_type, round) combination the vectors actually exercise,
    // so this pin never drifts out of sync with the suite it stands in for.
    let mut combos: Vec<(String, i64)> = cases
        .iter()
        .map(|case| {
            let input = &case["input"];
            (
                input["duty_type_name"].as_str().unwrap().to_string(),
                input["round"].as_i64().unwrap(),
            )
        })
        .collect::<HashSet<_>>()
        .into_iter()
        .collect();
    combos.sort();
    assert_eq!(
        combos.len(),
        24,
        "expected 6 duty types x 4 rounds = 24 distinct (duty_type, round) combinations"
    );

    let timer_func = get_round_timer_func(feature_set_with_proposal_timeout_enabled());
    // The vectors' own slot extremes: 0, 1, and a slot far into an epoch
    // (7231) -- as wide a spread as the vectors themselves test.
    let (slot_a, slot_b) = (0u64, 7231u64);

    let mut failures = Vec::new();
    for (duty_type_name, round) in combos {
        let duty_type = duty_type_from_name(&duty_type_name);

        let duty_a = Duty::new(SlotNumber::from(slot_a), duty_type.clone());
        let timer_a = timer_func(duty_a);
        let got_a = measure_round_timeout(timer_a.as_ref(), round).await;

        let duty_b = Duty::new(SlotNumber::from(slot_b), duty_type);
        let timer_b = timer_func(duty_b);
        let got_b = measure_round_timeout(timer_b.as_ref(), round).await;

        if got_a != got_b {
            failures.push(format!(
                "timer_deadlines/slot_invariance/{duty_type_name}_round{round}: \
                 slot {slot_a} gave {got_a:?}, slot {slot_b} gave {got_b:?}"
            ));
        }
    }

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
