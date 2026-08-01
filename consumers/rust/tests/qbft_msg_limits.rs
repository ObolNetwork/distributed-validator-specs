//! Runs the `qbft_msg_limits` suite against pluto's QBFT message intake.
//!
//! The vectors describe the spec's amplification limits on an inbound
//! `QbftConsensusMsg`: `justifications <= 2*nodes`, `values <=
//! 2*(justifications+1)`, and a wire size of at most 32 MiB. Pluto does not
//! implement either count limit as the spec states it:
//!
//! - Justifications: pluto's own cap is `4 * node_count()` (component.rs
//!   `MAX_JUSTIFICATIONS_PER_NODE = 4`, checked with a strict `>`), not the
//!   spec's `2n`. This is unilateral defensive hardening pluto chose
//!   (documented in its own doc comment as bounding secp256k1-recovery work,
//!   independent of charon), not a charon v1.7.1 behaviour and not the
//!   spec's formula either. See Findings.
//! - Values: there is no length check on `QbftConsensusMsg.values` anywhere
//!   in `crates/consensus/src` or `crates/core/src` — confirmed by
//!   exhaustive grep. `values_by_hash` iterates an unbounded `Vec<Any>`.
//!
//! Both gaps match the `charon_anchor.json` ladder entry "QBFT
//! DECIDED-resend rate limit and message size/count limits"
//! (`first_charon_release: null` — absent from every released charon, so
//! pluto legitimately trails it at the v1.7.1 anchor). Every `counts` vector
//! case whose `justification_count` sits between the spec's `2n+1` and
//! pluto's `4n` is therefore an ABSENT-OK divergence: the spec says reject,
//! pluto accepts, and no ladder entry excuses over-rejection in the other
//! direction. `counts` below proves structurally (not by case name) that
//! every vector case's `justification_count` stays at or under pluto's `4n`,
//! so pluto is expected to accept every one of the 11 cases regardless of
//! what the spec says; a rejection would be a real FAIL (over-rejection
//! breaks liveness) and is reported as such.
//!
//! Because the vectors never probe pluto's own `4n` boundary (its largest
//! `nodes=4` case only reaches `justification_count=9`, far under `4*4=16`),
//! `pluto_own_justification_cap_accepts_at_boundary` and
//! `pluto_own_justification_cap_rejects_one_over_boundary` pin that contract
//! directly against real messages, independent of the vector file.
//!
//! `wire_size` exercises the actual reader pluto's QBFT p2p layer uses
//! (`pluto_p2p::proto::read_protobuf_with_max_size`) with the 32 MiB
//! consensus-specific limit, mirroring `crates/consensus/src/qbft/p2p.rs`'s
//! own unit tests (`reference_framed_message_decodes`,
//! `inbound_rejects_message_exceeding_max_consensus_size`), including their
//! `futures::io::Cursor` in-memory stream — the brief suggested
//! `tokio::io::duplex`, but pluto's own reference tests use `Cursor`, which
//! needs no additional dependency or feature and exercises the identical
//! `AsyncRead` code path.

use std::sync::Arc;

use futures::io::Cursor;
use k256::SecretKey;
use prost::Message;
use prost_types::Any;
use tokio_util::sync::CancellationToken;

use pluto_consensus::qbft::msg::hash_proto;
use pluto_consensus::qbft::{Config, Consensus, Error, Peer};
use pluto_consensus::timer::get_round_timer_func;
use pluto_core::corepb::v1::{consensus as pbconsensus, core as pbcore};
use pluto_core::deadline::{DeadlineCalculator, DeadlinerTask};
use pluto_core::qbft::{MSG_PRE_PREPARE, MSG_ROUND_CHANGE};
use pluto_core::types::{Duty, DutyType, SlotNumber};
use pluto_featureset::FeatureSet;
use spec_vectors_pluto::load_suite;

/// Pluto's own hardening cap (`crates/consensus/src/qbft/component.rs`
/// `MAX_JUSTIFICATIONS_PER_NODE`), unrelated to the spec's `2n`. See the
/// module doc comment.
const PLUTO_MAX_JUSTIFICATIONS_PER_NODE: usize = 4;

fn secret_key(seed: u8) -> SecretKey {
    SecretKey::from_slice(&[seed; 32]).expect("valid seed bytes")
}

fn build_peers(nodes: usize) -> Vec<Peer> {
    (0..nodes)
        .map(|i| Peer {
            index: i64::try_from(i).expect("small node count fits i64"),
            name: format!("node-{i}"),
            public_key: secret_key(u8::try_from(i + 1).expect("small seed fits u8")).public_key(),
        })
        .collect()
}

/// A `DeadlineCalculator` that always reports a deadline an hour in the
/// future, so `Consensus::handle`'s `add_deadline` call always yields
/// `AddOutcome::Scheduled`.
///
/// Pluto's public `NeverExpiringCalculator` looks like the obvious fit here,
/// but it returns `Ok(None)` ("no deadline"), which `handle`'s admission
/// check (`add_deadline(...).await != AddOutcome::Scheduled`) treats as a
/// rejection (`Error::DutyExpired`) -- `NoDeadline` is *not* `Scheduled`.
/// This mirrors pluto's own internal test helper `FutureCalculator`
/// (`crates/consensus/src/qbft/component.rs`, used via `config_base(false)`
/// for exactly this reason).
struct FutureDeadlineCalculator;

impl DeadlineCalculator for FutureDeadlineCalculator {
    fn deadline(
        &self,
        _duty: &Duty,
    ) -> pluto_core::deadline::Result<Option<chrono::DateTime<chrono::Utc>>> {
        Ok(Some(
            chrono::Utc::now()
                .checked_add_signed(chrono::Duration::hours(1))
                .expect("one hour ahead fits DateTime"),
        ))
    }
}

/// Builds a `Consensus` for `nodes` peers, wired the way
/// `crates/consensus/examples/qbft.rs`'s `build_consensus` does (see the
/// probe doc, section B.1). `DeadlinerHandle::always` turned out to be
/// `#[cfg(test)]`-gated inside pluto_core (not reachable from an external
/// crate, unlike what the probe doc's snippet showed), so this uses the
/// real public `DeadlinerTask::start` with `FutureDeadlineCalculator`
/// (see above) instead.
fn build_consensus(nodes: usize) -> Consensus {
    let (deadliner, expired_rx) = DeadlinerTask::start(
        CancellationToken::new(),
        "qbft-msg-limits-test",
        FutureDeadlineCalculator,
    );
    Consensus::new(Config {
        peers: build_peers(nodes),
        local_peer_idx: 0,
        privkey: secret_key(1),
        deadliner,
        expired_rx,
        duty_gater: Arc::new(|_: &Duty| true),
        broadcaster: Arc::new(|_, _| Box::pin(async { Ok(()) })),
        sniffer: Arc::new(|_| {}),
        compare_attestations: false,
        timer_func: get_round_timer_func(Arc::new(FeatureSet::default())),
        feature_set: Arc::new(FeatureSet::default()),
    })
    .expect("consensus construction with a valid local_peer_idx must succeed")
}

/// Reproduces pluto's own (crate-private) `qbft::msg::sign_msg`: clear the
/// signature, `hash_proto` the cleared message, sign the 32-byte root with
/// `pluto_k1util::sign`, reattach. `sign_msg` itself is `pub(crate)`;
/// `hash_proto` and `pluto_k1util::sign` are the public halves it is built
/// from (proven by Task 2's `qbft_hashing` and Task 1's
/// `secp256k1_signatures` suites respectively).
fn sign_qbft_msg(msg: &pbconsensus::QbftMsg, key: &SecretKey) -> pbconsensus::QbftMsg {
    let mut clone = msg.clone();
    clone.signature = Default::default();
    let hash = hash_proto(&clone).expect("hash_proto on a QbftMsg must succeed");
    let signature = pluto_k1util::sign(key, &hash).expect("sign must succeed");
    clone.signature = signature.to_vec().into();
    clone
}

fn duty() -> Duty {
    Duty::new(SlotNumber::from(42u64), DutyType::Attester)
}

/// A single, distinct, validly signed justification message for peer 0,
/// reused `justification_count` times per case -- exactly how pluto's own
/// internal `handle_rejects_too_many_justifications` /
/// `handle_accepts_max_justifications` tests build their fixtures
/// (`crates/consensus/src/qbft/component.rs`): the cap counts entries, not
/// distinct senders, so one repeated valid message is a faithful fixture.
fn signed_justification_msg() -> pbconsensus::QbftMsg {
    let unsigned = pbconsensus::QbftMsg {
        r#type: i64::from(MSG_ROUND_CHANGE),
        duty: Some(pbcore::Duty::try_from(&duty()).expect("valid duty converts")),
        peer_idx: 0,
        round: 1,
        prepared_round: 0,
        ..Default::default()
    };
    sign_qbft_msg(&unsigned, &secret_key(1))
}

fn signed_outer_msg() -> pbconsensus::QbftMsg {
    let unsigned = pbconsensus::QbftMsg {
        r#type: i64::from(MSG_PRE_PREPARE),
        duty: Some(pbcore::Duty::try_from(&duty()).expect("valid duty converts")),
        peer_idx: 0,
        round: 1,
        prepared_round: 0,
        ..Default::default()
    };
    sign_qbft_msg(&unsigned, &secret_key(1))
}

/// A minimal, decodable `values` entry. The outer message's `value_hash` is
/// left at its default (empty) in every case here, which `msg::Msg::new`
/// collapses to the nil hash requiring no lookup (confirmed in
/// `crates/consensus/src/qbft/msg.rs`'s `Msg::new` doc comment), so these
/// entries never need to match anything -- only to decode successfully via
/// `decode_supported_any`, which is all `values_by_hash` ever checks.
fn any_value(tag: u8) -> Any {
    Any::from_msg(&pbcore::UnsignedDataSet {
        set: [(format!("0x{tag:02x}"), vec![tag].into())].into(),
    })
    .expect("pack UnsignedDataSet")
}

fn build_consensus_msg(
    justification_count: usize,
    value_count: usize,
) -> pbconsensus::QbftConsensusMsg {
    pbconsensus::QbftConsensusMsg {
        msg: Some(signed_outer_msg()),
        justification: std::iter::repeat_n(signed_justification_msg(), justification_count)
            .collect(),
        values: (0..value_count)
            .map(|i| any_value(u8::try_from(i % 256).expect("masked to u8 range")))
            .collect(),
    }
}

#[tokio::test]
async fn counts() {
    let suite = load_suite("qbft_msg_limits");
    let cases = suite["counts"].as_array().unwrap();
    assert_eq!(cases.len(), 11, "expected 11 counts cases");

    let mut failures = Vec::new();
    let mut matched = 0usize;
    let mut absent_ok = 0usize;

    for case in cases {
        let name = case["name"].as_str().unwrap();
        let input = &case["input"];
        let nodes = input["nodes"].as_u64().unwrap() as usize;
        let justification_count = input["justification_count"].as_u64().unwrap() as usize;
        let value_count = input["value_count"].as_u64().unwrap() as usize;
        let spec_accepted = case["accepted"].as_bool().unwrap();
        let spec_reason = case["reason"].as_str();

        // Structural proof (not a name-list) that every counts case stays
        // within pluto's own 4n cap, so pluto is expected to accept it
        // unconditionally. If this ever breaks, the case needs re-triage
        // rather than an automatic ABSENT-OK.
        let pluto_max_justifications = PLUTO_MAX_JUSTIFICATIONS_PER_NODE * nodes;
        assert!(
            justification_count <= pluto_max_justifications,
            "qbft_msg_limits/counts/{name}: fixture assumption broken -- \
             justification_count {justification_count} exceeds pluto's own cap \
             {pluto_max_justifications}; this needs re-triage, not an unconditional accept"
        );

        let consensus = build_consensus(nodes);
        let msg = build_consensus_msg(justification_count, value_count);

        match consensus.handle(msg, &CancellationToken::new()).await {
            Ok(()) => {
                if spec_accepted {
                    matched += 1;
                } else {
                    // ABSENT-OK: the spec would reject (reason spec_reason),
                    // pluto accepts because it has no equivalent check at
                    // this input size. Ladder entry: "QBFT DECIDED-resend
                    // rate limit and message size/count limits"
                    // (first_charon_release: null).
                    absent_ok += 1;
                }
            }
            Err(err) => {
                failures.push(format!(
                    "qbft_msg_limits/counts/{name}: pluto rejected ({err:?}) with \
                     nodes={nodes} justification_count={justification_count} \
                     value_count={value_count}; spec accepted={spec_accepted} \
                     reason={spec_reason:?} -- unexpected over-rejection, no ladder \
                     entry excuses this"
                ));
            }
        }
    }

    assert_eq!(
        matched, 5,
        "expected 5 cases where pluto's acceptance matches the spec"
    );
    assert_eq!(
        absent_ok, 6,
        "expected 6 ABSENT-OK cases (pluto's 4n justification cap / absent values cap)"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Pins pluto's real contract at its own boundary: exactly `4 * node_count()`
/// justifications must be accepted (the check is a strict `>`, per
/// `component.rs`). No vector case reaches this boundary (the largest,
/// `nodes=4`, only goes to `justification_count=9` against `4*4=16`), so
/// without this test pluto's actual cap is asserted only in a doc comment.
#[tokio::test]
async fn pluto_own_justification_cap_accepts_at_boundary() {
    let nodes = 4;
    let consensus = build_consensus(nodes);
    let max = PLUTO_MAX_JUSTIFICATIONS_PER_NODE * nodes;
    let msg = build_consensus_msg(max, 0);

    consensus
        .handle(msg, &CancellationToken::new())
        .await
        .expect("exactly 4*nodes justifications must be accepted (strict `>` comparison)");
}

/// Companion to the above: one past pluto's own boundary must be rejected
/// with `Error::TooManyJustifications`, and the reported `count`/`max` must
/// match exactly -- asserting the reason, not just that it failed.
#[tokio::test]
async fn pluto_own_justification_cap_rejects_one_over_boundary() {
    let nodes = 4;
    let consensus = build_consensus(nodes);
    let max = PLUTO_MAX_JUSTIFICATIONS_PER_NODE * nodes;
    let msg = build_consensus_msg(max + 1, 0);

    let err = consensus
        .handle(msg, &CancellationToken::new())
        .await
        .expect_err("4*nodes + 1 justifications must be rejected");

    match err {
        Error::TooManyJustifications {
            count,
            max: reported_max,
        } => {
            assert_eq!(count, max + 1);
            assert_eq!(reported_max, max);
        }
        other => panic!("expected Error::TooManyJustifications, got {other:?}"),
    }
}

#[test]
fn wire_size_constants() {
    // The 32 MiB consensus limit is a narrowing of libp2p's 128 MiB default;
    // both constants are public in pluto.
    assert_eq!(
        pluto_consensus::qbft::p2p::MAX_CONSENSUS_MSG_SIZE,
        32 * 1024 * 1024
    );
    assert_eq!(pluto_p2p::proto::MAX_MESSAGE_SIZE, 128 << 20);
}

/// LEB128 varint length-prefix, replicating pluto's own
/// `inbound_rejects_message_exceeding_max_consensus_size` test
/// (`crates/consensus/src/qbft/p2p.rs`). `read_length_delimited` rejects an
/// oversized declared length as soon as it reads this prefix, before ever
/// reading a body -- so oversized rejected cases below need only these few
/// bytes, never a multi-hundred-megabyte buffer.
fn varint_len_prefix(mut remaining: usize) -> Vec<u8> {
    let mut varint = Vec::new();
    loop {
        let mut byte = u8::try_from(remaining & 0x7f).expect("7-bit masked value fits in u8");
        remaining >>= 7;
        if remaining != 0 {
            byte |= 0x80;
        }
        varint.push(byte);
        if remaining == 0 {
            break;
        }
    }
    varint
}

/// Builds a `QbftConsensusMsg` whose encoded length is exactly `target_len`
/// bytes, by padding a single `values` entry's `Any.value`. Converges in a
/// handful of iterations: the only overhead is protobuf tag/length-prefix
/// bytes, which only change size at varint-width boundaries.
fn qbft_consensus_msg_of_encoded_len(target_len: usize) -> pbconsensus::QbftConsensusMsg {
    let mut padding_len = target_len;
    for _ in 0..16 {
        let candidate = pbconsensus::QbftConsensusMsg {
            msg: None,
            justification: vec![],
            values: vec![Any {
                type_url: String::new(),
                value: vec![0u8; padding_len],
            }],
        };
        let encoded_len = candidate.encoded_len();
        if encoded_len == target_len {
            return candidate;
        }
        let diff = i64::try_from(encoded_len).expect("size fits i64")
            - i64::try_from(target_len).expect("size fits i64");
        padding_len = usize::try_from(i64::try_from(padding_len).expect("size fits i64") - diff)
            .expect("padding length stays non-negative while sizing the test message");
    }
    panic!("qbft_consensus_msg_of_encoded_len({target_len}) did not converge");
}

/// Mirrors how `crates/consensus/src/qbft/p2p.rs`'s own tests
/// (`reference_framed_message_decodes`,
/// `inbound_rejects_message_exceeding_max_consensus_size`) invoke
/// `read_protobuf_with_max_size` with `MAX_CONSENSUS_MSG_SIZE`, over the same
/// `futures::io::Cursor` in-memory stream type.
///
/// Matching on `err.to_string()` below is in tension with
/// `test_vectors/README.md`'s rule that the slugs are the contract and the
/// wording of an error message is not:
/// it is unavoidable here because every rejection path in
/// `read_protobuf_with_max_size` reports through the same `io::ErrorKind::InvalidData`
/// with no structured reason code, and pluto's own `p2p.rs` tests assert the
/// same substring for the same reason.
#[tokio::test]
async fn wire_size_enforcement() {
    let suite = load_suite("qbft_msg_limits");
    let cases = suite["wire_size"].as_array().unwrap();
    assert_eq!(cases.len(), 4, "expected 4 wire_size cases");

    let mut failures = Vec::new();
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let wire_size_bytes = case["input"]["wire_size_bytes"].as_u64().unwrap() as usize;
        let accepted = case["accepted"].as_bool().unwrap();

        if accepted {
            let msg = qbft_consensus_msg_of_encoded_len(wire_size_bytes);
            assert_eq!(
                msg.encoded_len(),
                wire_size_bytes,
                "qbft_msg_limits/wire_size/{name}: test fixture sizing bug"
            );

            let mut cursor = Cursor::new(Vec::new());
            pluto_p2p::proto::write_protobuf(&mut cursor, &msg)
                .await
                .expect("frame write should succeed");
            cursor.set_position(0);

            match pluto_p2p::proto::read_protobuf_with_max_size::<pbconsensus::QbftConsensusMsg, _>(
                &mut cursor,
                pluto_consensus::qbft::p2p::MAX_CONSENSUS_MSG_SIZE,
            )
            .await
            {
                Ok(decoded) if decoded == msg => {}
                Ok(_) => failures.push(format!(
                    "qbft_msg_limits/wire_size/{name}: decoded message did not round-trip"
                )),
                Err(err) => failures.push(format!(
                    "qbft_msg_limits/wire_size/{name}: expected accept at {wire_size_bytes} \
                     bytes, got {err}"
                )),
            }
        } else {
            let mut cursor = Cursor::new(varint_len_prefix(wire_size_bytes));

            match pluto_p2p::proto::read_protobuf_with_max_size::<pbconsensus::QbftConsensusMsg, _>(
                &mut cursor,
                pluto_consensus::qbft::p2p::MAX_CONSENSUS_MSG_SIZE,
            )
            .await
            {
                Ok(_) => failures.push(format!(
                    "qbft_msg_limits/wire_size/{name}: expected reject at {wire_size_bytes} \
                     bytes, got Ok"
                )),
                Err(err) => {
                    // Assert the reason ("msg_too_large"), not just that it
                    // failed: `read_length_delimited` reports oversized
                    // frames with this exact wording.
                    let text = err.to_string();
                    if !text.contains("too large") {
                        failures.push(format!(
                            "qbft_msg_limits/wire_size/{name}: rejected for the wrong reason: \
                             {text} (want a \"too large\" message-size error)"
                        ));
                    }
                }
            }
        }
    }

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
