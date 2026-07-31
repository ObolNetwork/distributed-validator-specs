//! Runs the `timer_deadlines` suite against pluto's consensus round timers.
//!
//! Pluto's timers are purely relative to `round`. The stored `Duty` on each
//! timer is read in exactly one place in `crates/consensus/src/timer.rs`:
//! `is_proposer`, used by `proposal_timeout_duration` to pick the round-1
//! proposer override. Nothing reads genesis time, slot duration, or slot
//! number. That splits the vectors' three columns:
//!
//! - `round_timeout_nanos`: tested below, against `RoundTimer::timer(round)`.
//! - `deadline_nanos` (absolute, genesis-derived): ABSENT-OK. Pluto's timers
//!   never compute an absolute deadline from genesis; the deterministic,
//!   genesis-derived eager-double-linear deadline is the
//!   `charon_anchor.json` behaviours-ladder entry "Deterministic
//!   (genesis-derived) eager double linear round deadlines"
//!   (`first_charon_release: v1.9.0`), which is later than pluto's v1.7.1
//!   parity anchor. This pin is intentionally not asserted in code: there is
//!   nothing in pluto to assert against, only its absence.
//! - `duty_start_delay_nanos`: UNREACHABLE. It lives in `delay_slot_offset`
//!   in `crates/core/src/scheduler.rs`, an `async fn` with no `pub` modifier
//!   and no external caller.

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
async fn round_timeouts() {
    let suite = load_suite("timer_deadlines");
    let cases = suite["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 216, "expected 216 timer_deadlines cases");

    // The vectors are the eager double linear timer plus the proposer
    // round-1 override. `EagerDoubleLinear` is Stable (enabled by
    // `Config::default`'s `min_status: Stable`); `ProposalTimeout` is Alpha
    // and must be turned on explicitly to get the proposer round-1
    // override the vectors encode; `Linear` stays off (its default).  With
    // `Linear` disabled, `get_round_timer_func` selects
    // `EagerDoubleLinearRoundTimer` for every duty type -- confirmed
    // against `get_round_timer_func`'s own branching and its
    // `get_timer_func` unit test in `timer.rs`.
    let feature_set = Arc::new(
        FeatureSet::from_config(Config {
            min_status: Status::Stable,
            enabled: vec![Feature::ProposalTimeout],
            disabled: vec![],
        })
        .expect("valid feature config"),
    );
    let timer_func = get_round_timer_func(feature_set);

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
                "timer_deadlines/{name}: round timeout {got:?}, want {want:?}"
            ));
        }
    }

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
