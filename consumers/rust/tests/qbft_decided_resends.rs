//! Runs the `qbft_decided_resends` suite directly against pluto's core QBFT
//! state machine (`pluto_core::qbft::run`), one level below the `Consensus`
//! wrapper Task 7 (`qbft_msg_limits`) exercises.
//!
//! The vectors describe the spec's post-decision rebroadcast limiter: once an
//! instance has decided, a ROUND-CHANGE should trigger at most one DECIDED
//! rebroadcast per source per strictly-increasing round, capped at 16 per
//! source. Pluto implements no such limiter -- confirmed here by driving a
//! real instance to DECIDED and observing its behaviour, not by code
//! inspection alone (`crates/core/src/qbft/mod.rs`'s main `recv(t.receive)`
//! arm, inside the `if let Some(v) = q_commit.as_ref() ...` branch): every
//! inbound `MSG_ROUND_CHANGE` from a source other than the deciding process
//! rebroadcasts DECIDED, unconditionally, regardless of round or repetition.
//! Ladder entry "QBFT DECIDED-resend rate limit and message size/count
//! limits" has `first_charon_release: null`, so this gap is ABSENT-OK: no
//! released charon carries the limiter either, at pluto's charon-v1.7.1
//! anchor.
//!
//! Two readings are checked per event, per the task brief:
//! - **pin reading** (asserted, must pass): pluto rebroadcasts DECIDED on
//!   every post-decision ROUND-CHANGE from another source. This is what
//!   actually happens today; if pluto ever adds the limiter, some of these
//!   assertions will start failing, which is the point -- the test is
//!   supposed to flip loudly rather than silently keep passing.
//! - **spec reading** (reported, not asserted): the vector's `rebroadcast`
//!   array, which encodes the limiter pluto lacks. Mismatches are counted and
//!   printed per case; they are expected once a source repeats/lowers a
//!   round or exceeds 16 rebroadcasts.

use std::sync::Arc;
use std::thread;
use std::time::Duration;

use cancellation::CancellationTokenSource;
use crossbeam::channel as mpmc;

use pluto_core::qbft::{
    self, BroadcastRequest, CompareRequest, DecideRequest, Definition, LeaderRequest, MSG_COMMIT,
    MSG_DECIDED, MSG_PRE_PREPARE, MSG_PREPARE, MSG_ROUND_CHANGE, MessageType, Msg, QbftError,
    QbftLogger, QbftTypes, RoundChangeLog, SomeMsg, Timer, Transport, UnjustLog, UponRuleLog,
};
use spec_vectors_pluto::load_suite;

/// Local process under test. Fixed across all cases; never the leader and
/// never one of the vector's event sources, so it can only ever be on the
/// receiving end of a rebroadcast decision.
const PROCESS: i64 = 0;
const VALUE: i64 = 7;
/// Generous but bounded: pluto's rebroadcast happens synchronously in the
/// same message-processing loop, so a real rebroadcast arrives near-
/// instantly. This only gets exhausted if pluto stops rebroadcasting, which
/// is itself a (loud, intended) test failure.
const RECV_TIMEOUT: Duration = Duration::from_secs(2);

struct TestTypes;

impl QbftTypes for TestTypes {
    type Instance = i64;
    type Value = i64;
    type Compare = i64;
}

/// Minimal external `SomeMsg` implementation, mirroring pluto's own
/// `internal_test.rs::TestMsg` (`crates/core/src/qbft/internal_test.rs`).
/// None of the post-decision ROUND-CHANGE events need real justification --
/// confirmed by reading `mod.rs`: once `q_commit` is set, the early-return
/// branch never calls `is_justified`, so `prepared_round`/`prepared_value`/
/// `justification` go unused for those messages.
#[derive(Debug, Clone)]
struct TestMsg {
    kind: MessageType,
    source: i64,
    round: i64,
    value: i64,
}

impl TestMsg {
    fn pre_prepare(source: i64, round: i64, value: i64) -> Msg<TestTypes> {
        Arc::new(TestMsg {
            kind: MSG_PRE_PREPARE,
            source,
            round,
            value,
        })
    }

    fn prepare(source: i64, round: i64, value: i64) -> Msg<TestTypes> {
        Arc::new(TestMsg {
            kind: MSG_PREPARE,
            source,
            round,
            value,
        })
    }

    fn commit(source: i64, round: i64, value: i64) -> Msg<TestTypes> {
        Arc::new(TestMsg {
            kind: MSG_COMMIT,
            source,
            round,
            value,
        })
    }

    fn round_change(source: i64, round: i64) -> Msg<TestTypes> {
        Arc::new(TestMsg {
            kind: MSG_ROUND_CHANGE,
            source,
            round,
            value: 0,
        })
    }
}

impl SomeMsg<TestTypes> for TestMsg {
    fn type_(&self) -> MessageType {
        self.kind
    }

    fn instance(&self) -> i64 {
        0
    }

    fn source(&self) -> i64 {
        self.source
    }

    fn round(&self) -> i64 {
        self.round
    }

    fn value(&self) -> i64 {
        self.value
    }

    fn value_source(&self) -> std::result::Result<i64, QbftError> {
        Ok(0)
    }

    fn prepared_round(&self) -> i64 {
        0
    }

    fn prepared_value(&self) -> i64 {
        0
    }

    fn justification(&self) -> Vec<Msg<TestTypes>> {
        vec![]
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

/// Runs a `qbft::run` instance on a background thread, feeds it the minimal
/// justified message sequence pluto's own `broadcast_request_maps_protocol_fields`
/// test uses (`crates/core/src/qbft/internal_test.rs`) to reach quorum
/// PREPARE and quorum COMMIT at round 1, then confirms decision was actually
/// reached before handing control back -- so a harness bug (failure to
/// decide) can never be mistaken for a conformance result.
struct Harness {
    receive_tx: mpmc::Sender<Msg<TestTypes>>,
    decided_rx: mpmc::Receiver<()>,
    cts: CancellationTokenSource,
    join: thread::JoinHandle<std::result::Result<(), QbftError>>,
    // Kept alive only so `run`'s `input_value_ch`/`input_value_source_ch`
    // channels stay open (a disconnected channel would make `run` error out
    // via its `mpmc::select!` arm). Never written to.
    _input_tx: mpmc::Sender<i64>,
    _source_tx: mpmc::Sender<i64>,
}

impl Harness {
    fn shutdown(self) {
        self.cts.cancel();
        let outcome = self.join.join().expect("qbft::run thread must not panic");
        assert!(
            matches!(outcome, Err(QbftError::ContextCanceled)),
            "expected ContextCanceled on shutdown, got {outcome:?}"
        );
    }
}

fn spawn_decided_instance(nodes: i64, decided_round: i64) -> Harness {
    assert_eq!(
        decided_round, 1,
        "harness only drives a round-1 decision (the minimal justified sequence from \
         pluto's own internal_test.rs); case has decided_round={decided_round}, which needs \
         a round-change dance this harness does not implement"
    );
    assert!(
        nodes >= 2,
        "need at least one external process to act as leader; got nodes={nodes}"
    );

    let others: Vec<i64> = (0..nodes).filter(|&p| p != PROCESS).collect();
    let need = usize::try_from(qbft::quorum(nodes)).expect("quorum fits usize");
    assert!(
        others.len() >= need,
        "not enough external processes ({}) to reach quorum ({need}) for nodes={nodes}",
        others.len()
    );
    let leader = others[0];

    let (receive_tx, receive_rx) = mpmc::unbounded::<Msg<TestTypes>>();
    let (decided_tx, decided_rx) = mpmc::unbounded::<()>();
    let (_input_tx, input_rx) = mpmc::bounded::<i64>(1);
    let (_source_tx, source_rx) = mpmc::bounded::<i64>(1);

    let cts = CancellationTokenSource::new();
    let token = cts.token().clone();

    let def = Definition::<TestTypes> {
        is_leader: Box::new(move |req: LeaderRequest<'_, TestTypes>| req.process == leader),
        new_timer: Box::new(|_round: i64| Timer {
            // Never fires: round timeouts must not inject unscripted events.
            receive: mpmc::never(),
            stop: Box::new(|| {}),
        }),
        compare: Arc::new(|req: CompareRequest<'_, TestTypes>| {
            req.return_err
                .send(Ok(()))
                .expect("compare return channel open");
        }),
        decide: Box::new(|_req: DecideRequest<'_, TestTypes>| {}),
        logger: QbftLogger {
            upon_rule: Box::new(|_: UponRuleLog<'_, TestTypes>| {}),
            round_change: Box::new(|_: RoundChangeLog<'_, TestTypes>| {}),
            unjust: Box::new(|_: UnjustLog<'_, TestTypes>| {}),
        },
        nodes,
        fifo_limit: 100,
    };

    let transport = Transport::<TestTypes> {
        broadcast: Box::new(move |req: BroadcastRequest<'_, TestTypes>| {
            if req.type_ == MSG_DECIDED {
                decided_tx.send(()).expect("decided channel open");
            }
            Ok(())
        }),
        receive: receive_rx,
    };

    let join = thread::spawn(move || {
        qbft::run(
            &token, &def, &transport, &0i64, PROCESS, input_rx, source_rx,
        )
    });

    // Minimal justified sequence to reach DECIDED at round 1: 1 PRE-PREPARE
    // from the leader, a quorum of PREPAREs, then a quorum of COMMITs
    // (mirrors `broadcast_request_maps_protocol_fields`,
    // `crates/core/src/qbft/internal_test.rs`).
    receive_tx
        .send(TestMsg::pre_prepare(leader, 1, VALUE))
        .expect("receive channel open");
    for &source in others.iter().take(need) {
        receive_tx
            .send(TestMsg::prepare(source, 1, VALUE))
            .expect("receive channel open");
    }
    for &source in others.iter().take(need) {
        receive_tx
            .send(TestMsg::commit(source, 1, VALUE))
            .expect("receive channel open");
    }

    // Warm-up: confirm the instance actually decided before measuring
    // anything. A round-change from the leader at an arbitrary round is not
    // part of any vector's event sequence, so consuming its rebroadcast here
    // cannot skew the measured events below.
    receive_tx
        .send(TestMsg::round_change(leader, 999))
        .expect("receive channel open");
    decided_rx.recv_timeout(RECV_TIMEOUT).unwrap_or_else(|_| {
        panic!(
            "harness failed to reach DECIDED: no DECIDED rebroadcast observed for the warm-up \
             ROUND-CHANGE within {RECV_TIMEOUT:?}"
        )
    });

    Harness {
        receive_tx,
        decided_rx,
        cts,
        join,
        _input_tx,
        _source_tx,
    }
}

#[test]
fn qbft_decided_resends() {
    let suite = load_suite("qbft_decided_resends");
    let cases = suite["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 2, "expected 2 qbft_decided_resends cases");

    let mut pin_failures = Vec::new();
    let mut report = String::new();

    for case in cases {
        let name = case["name"].as_str().unwrap();
        let input = &case["input"];
        let nodes = input["nodes"].as_i64().unwrap();
        let decided_round = input["decided_round"].as_i64().unwrap();
        let events: Vec<(i64, i64)> = input["events"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| (e["source"].as_i64().unwrap(), e["round"].as_i64().unwrap()))
            .collect();
        let spec_rebroadcast: Vec<bool> = case["rebroadcast"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_bool().unwrap())
            .collect();
        let spec_total = case["total_rebroadcasts"].as_u64().unwrap() as usize;

        assert_eq!(
            events.len(),
            spec_rebroadcast.len(),
            "qbft_decided_resends/{name}: events/rebroadcast length mismatch"
        );
        assert_eq!(
            spec_rebroadcast.iter().filter(|&&b| b).count(),
            spec_total,
            "qbft_decided_resends/{name}: vector's total_rebroadcasts disagrees with its own \
             rebroadcast array"
        );

        let harness = spawn_decided_instance(nodes, decided_round);

        let mut actual = Vec::with_capacity(events.len());
        for &(source, round) in &events {
            harness
                .receive_tx
                .send(TestMsg::round_change(source, round))
                .expect("receive channel open");
            actual.push(harness.decided_rx.recv_timeout(RECV_TIMEOUT).is_ok());
        }

        for (i, (&got, &(source, round))) in actual.iter().zip(events.iter()).enumerate() {
            // Pin reading: pluto rebroadcasts DECIDED on every post-decision
            // ROUND-CHANGE from a source other than the deciding process --
            // no per-source cap, no round-monotonicity check. Every event
            // here has source != PROCESS, so every one must rebroadcast. If
            // pluto ever adds the ladder's limiter, some entries will flip
            // to `false` and this assertion fails loudly, as intended.
            if !got {
                pin_failures.push(format!(
                    "qbft_decided_resends/{name}: event {i} (source={source}, round={round}) \
                     did not trigger a DECIDED rebroadcast; pluto's pinned no-limiter rule \
                     expects every post-decision ROUND-CHANGE from another source to rebroadcast"
                ));
            }
        }

        let spec_mismatches = actual
            .iter()
            .zip(spec_rebroadcast.iter())
            .filter(|(a, s)| a != s)
            .count();
        report.push_str(&format!(
            "qbft_decided_resends/{name}: {spec_mismatches}/{} events diverge from the spec \
             reading (ABSENT-OK -- pluto has no resend rate/round limiter; ladder entry \
             \"QBFT DECIDED-resend rate limit and message size/count limits\", \
             first_charon_release: null)\n",
            events.len()
        ));

        harness.shutdown();
    }

    println!("{report}");
    assert!(pin_failures.is_empty(), "{}", pin_failures.join("\n"));
}
