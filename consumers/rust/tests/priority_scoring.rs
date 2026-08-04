//! Conformance suite: `priority_scoring` against pluto's `Prioritiser`.
//!
//! `calculate_result` (`pluto_priority::calculate`) is `pub(crate)`, so this
//! drives it end-to-end through the public `Prioritiser` API over an
//! in-process libp2p network, with a mock `Consensus` that captures the
//! proposed `PriorityResult` (mirrors
//! `pluto/crates/priority/tests/prioritiser_test.rs`, which is itself an
//! external-style test using only public API).

use std::{
    collections::{HashMap, HashSet},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};

use async_trait::async_trait;
use futures::{FutureExt as _, StreamExt as _, future::select_all};
use k256::{SecretKey, elliptic_curve::rand_core::OsRng};
use libp2p::{
    Multiaddr, PeerId, Swarm,
    core::{Transport as _, transport::MemoryTransport, upgrade::Version},
    multiaddr::Protocol,
    swarm::SwarmEvent,
};
use pluto_core::{
    corepb::v1::{
        core::Duty as ProtoDuty,
        priority::{PriorityMsg, PriorityResult, PriorityTopicProposal},
    },
    deadline::{DeadlineCalculator, DeadlinerHandle, DeadlinerTask},
    types::Duty,
};
use pluto_p2p::{p2p_context::P2PContext, peer::peer_id_from_key, utils::keypair_from_secret_key};
use pluto_priority::{
    Consensus, ConsensusError, Prioritiser, PrioritySubscriber,
    component::{TopicProposal, TopicResult, sign_msg},
    p2p::Behaviour,
};
use spec_vectors_pluto::load_suite;
use tokio::{sync::oneshot, time::timeout};
use tokio_util::sync::CancellationToken;

/// Calculator that schedules every duty one hour out, so `DeadlinerHandle::add`
/// returns `Scheduled` rather than dropping the instance as expired.
struct FutureCalculator;

impl DeadlineCalculator for FutureCalculator {
    fn deadline(
        &self,
        _duty: &Duty,
    ) -> pluto_core::deadline::Result<Option<chrono::DateTime<chrono::Utc>>> {
        Ok(Some(
            chrono::Utc::now()
                .checked_add_signed(chrono::Duration::hours(1))
                .expect("deadline in range"),
        ))
    }
}

/// Mock consensus that decides on the first proposal per duty by invoking its
/// subscribers, and asserts every subsequent proposal for that duty is
/// identical. Verbatim shape from `prioritiser_test.rs`'s `TestConsensus`.
#[derive(Default)]
struct MockConsensus {
    subs: Mutex<Vec<PrioritySubscriber>>,
    proposed: Mutex<HashMap<u64, PriorityResult>>,
}

#[async_trait]
impl Consensus for MockConsensus {
    async fn propose_priority(
        &self,
        duty: Duty,
        result: PriorityResult,
        _ct: &CancellationToken,
    ) -> Result<(), ConsensusError> {
        let slot = duty.slot.inner();
        {
            let proposed = self.proposed.lock().expect("proposed mutex");
            if let Some(prev) = proposed.get(&slot) {
                assert_eq!(
                    prev.topics, result.topics,
                    "all proposals for a duty must be identical"
                );
                return Ok(());
            }
        }
        let subs = self.subs.lock().expect("subs mutex");
        for sub in subs.iter() {
            sub(duty.clone(), result.clone())?;
        }
        drop(subs);
        self.proposed
            .lock()
            .expect("proposed mutex")
            .insert(slot, result);
        Ok(())
    }

    fn subscribe_priority(&self, callback: PrioritySubscriber) {
        self.subs.lock().expect("subs mutex").push(callback);
    }
}

/// A built in-process host: its swarm, prioritiser, and listen address.
struct Host {
    swarm: Swarm<Behaviour>,
    prioritiser: Prioritiser,
    addr: Multiaddr,
}

/// Global counter for in-process memory-transport addresses.
///
/// Addresses must never repeat across cases within one test run: aborting a
/// prior case's swarm driver doesn't synchronously release its listener from
/// `MemoryTransport`'s global address registry, so reusing an address (e.g.
/// restarting from seed 0 each case) intermittently fails a later case's
/// `listen_on` with `Unreachable`.
static NEXT_MEMORY_ADDR: AtomicU64 = AtomicU64::new(1);

/// Returns a fresh, never-reused `/memory/<n>` address.
fn memory_addr() -> Multiaddr {
    Multiaddr::empty().with(Protocol::Memory(
        NEXT_MEMORY_ADDR.fetch_add(1, Ordering::Relaxed),
    ))
}

/// Builds one host wired to the shared `consensus` and `deadliner`, running
/// its priority behaviour over an in-process `MemoryTransport`.
fn build_host(
    secret: SecretKey,
    peer_id: PeerId,
    peers: Vec<PeerId>,
    min_required: i64,
    consensus: Arc<dyn Consensus>,
    deadliner: DeadlinerHandle,
    exchange_timeout: Duration,
) -> Host {
    let keypair = keypair_from_secret_key(secret).expect("keypair");
    let validator = Box::new(|_: &PriorityMsg| Ok(()));

    let (prioritiser, behaviour) = Prioritiser::new_internal(
        peer_id,
        peers.clone(),
        min_required,
        consensus,
        validator,
        exchange_timeout,
        deadliner,
        P2PContext::new(peers),
    );

    let swarm = libp2p::SwarmBuilder::with_existing_identity(keypair)
        .with_tokio()
        .with_other_transport(|key| {
            MemoryTransport::default()
                .upgrade(Version::V1)
                .authenticate(libp2p::noise::Config::new(key).expect("noise config"))
                .multiplex(libp2p::yamux::Config::default())
        })
        .expect("transport")
        .with_behaviour(|_key| behaviour)
        .expect("behaviour")
        .build();

    Host {
        swarm,
        prioritiser,
        addr: memory_addr(),
    }
}

/// Builds a signed `PriorityMsg` proposing `priorities` for `topic`, plus an
/// empty proposal for `ignored_topic` (mirroring `calculate.rs`'s own
/// `build_msgs` test helper, which is the source of this suite's vectors).
fn build_msg(
    peer_id: PeerId,
    secret: &SecretKey,
    slot: u64,
    topic: &str,
    priorities: &[String],
    ignored_topic: &str,
) -> PriorityMsg {
    let topics = vec![
        PriorityTopicProposal::from(&TopicProposal {
            topic: topic.to_owned(),
            priorities: priorities.to_vec(),
        }),
        PriorityTopicProposal::from(&TopicProposal {
            topic: ignored_topic.to_owned(),
            priorities: Vec::new(),
        }),
    ];
    let msg = PriorityMsg {
        duty: Some(ProtoDuty { slot, r#type: 0 }),
        topics,
        peer_id: peer_id.to_string(),
        signature: Default::default(),
    };
    sign_msg(&msg, secret).expect("sign")
}

/// Runs one `priority_scoring` case end-to-end and returns the decided
/// `PriorityResult`.
///
/// Peer ordering is load-bearing: `calculate_result` sorts input messages by
/// peer id string and breaks score ties by first-seen order in that sorted
/// input, so the vector's peer "0", "1", ... assumes ascending peer-id order.
/// Generated keypairs are sorted by their derived `PeerId` string and mapped
/// onto the vector's peers in that order.
async fn run_case(input: &serde_json::Value) -> PriorityResult {
    let min_required = input["min_required"].as_i64().expect("min_required");
    let slot = input["slot"].as_u64().expect("slot");
    let topic = input["topic"].as_str().expect("topic");
    let ignored_topic = input["ignored_topic"].as_str().expect("ignored_topic");
    let peers_in = input["peers"].as_array().expect("peers");
    let n = peers_in.len();

    for (idx, p) in peers_in.iter().enumerate() {
        assert_eq!(
            p["peer_id"].as_str().expect("peer_id"),
            idx.to_string(),
            "vector peers must be indexed \"0\", \"1\", ... in order"
        );
    }

    let mut keyed: Vec<(SecretKey, PeerId)> = (0..n)
        .map(|_| {
            let key = SecretKey::random(&mut OsRng);
            let peer_id = peer_id_from_key(key.public_key()).expect("peer id");
            (key, peer_id)
        })
        .collect();
    keyed.sort_by_key(|(_, peer_id)| peer_id.to_string());

    let peers: Vec<PeerId> = keyed.iter().map(|(_, p)| *p).collect();
    let consensus = Arc::new(MockConsensus::default());
    let exchange_timeout = Duration::from_millis(500);

    // One deadliner shared across all of this case's hosts; the expired-duty
    // receiver is unused since this suite never calls `Prioritiser::start`
    // (no cleanup loop needed for a short-lived per-case network).
    let ct = CancellationToken::new();
    let (deadliner, _expired) =
        DeadlinerTask::start(ct.clone(), "priority_scoring", FutureCalculator);

    let mut hosts: Vec<Host> = Vec::with_capacity(n);
    for (key, peer_id) in &keyed {
        hosts.push(build_host(
            key.clone(),
            *peer_id,
            peers.clone(),
            min_required,
            consensus.clone(),
            deadliner.clone(),
            exchange_timeout,
        ));
    }

    // Capture the decided result once via a subscriber on host 0. Every host's
    // `Prioritiser::new_internal` registers a forwarding closure with the
    // shared `consensus`, so whichever host's exchange completes first still
    // invokes host 0's own subscriber (decide-once semantics).
    let (result_tx, result_rx) = oneshot::channel::<PriorityResult>();
    let result_tx = Arc::new(Mutex::new(Some(result_tx)));
    {
        let tx = result_tx.clone();
        hosts[0]
            .prioritiser
            .subscribe(Box::new(move |_duty, result| {
                if let Some(sender) = tx.lock().expect("lock").take() {
                    let _ = sender.send(result);
                }
                Ok(())
            }));
    }

    for host in &mut hosts {
        host.swarm.listen_on(host.addr.clone()).expect("listen");
    }
    for host in &mut hosts {
        loop {
            if matches!(
                host.swarm.select_next_some().await,
                SwarmEvent::NewListenAddr { .. }
            ) {
                break;
            }
        }
    }

    let addrs: Vec<Multiaddr> = hosts.iter().map(|h| h.addr.clone()).collect();
    for (i, host) in hosts.iter_mut().enumerate() {
        for (j, addr) in addrs.iter().enumerate() {
            if i != j {
                host.swarm.dial(addr.clone()).expect("dial");
            }
        }
    }

    if n > 1 {
        let mut connected: Vec<HashSet<PeerId>> = vec![HashSet::new(); n];
        let mesh = async {
            while connected.iter().any(|c| c.len() < n - 1) {
                let next = hosts
                    .iter_mut()
                    .map(|h| h.swarm.select_next_some().boxed())
                    .collect::<Vec<_>>();
                let (event, idx, _) = select_all(next).await;
                if let SwarmEvent::ConnectionEstablished { peer_id, .. } = event {
                    connected[idx].insert(peer_id);
                }
            }
        };
        timeout(Duration::from_secs(10), mesh)
            .await
            .expect("full connection mesh within timeout");
    }

    let mut msgs = Vec::with_capacity(n);
    for (idx, peer_json) in peers_in.iter().enumerate() {
        let priorities: Vec<String> = peer_json["priorities"]
            .as_array()
            .expect("priorities")
            .iter()
            .map(|v| v.as_str().expect("priority string").to_owned())
            .collect();
        let (key, peer_id) = &keyed[idx];
        msgs.push(build_msg(
            *peer_id,
            key,
            slot,
            topic,
            &priorities,
            ignored_topic,
        ));
    }

    let mut drivers = Vec::with_capacity(n);
    let mut prioritisers = Vec::with_capacity(n);
    for host in hosts.into_iter() {
        prioritisers.push(host.prioritiser);
        let mut swarm = host.swarm;
        drivers.push(tokio::spawn(async move {
            loop {
                let _ = swarm.select_next_some().await;
            }
        }));
    }

    let mut prioritise_tasks = Vec::with_capacity(n);
    for (prio, msg) in prioritisers.iter().zip(msgs) {
        let prio = prio.clone();
        let ct = ct.clone();
        prioritise_tasks.push(tokio::spawn(async move { prio.prioritise(msg, ct).await }));
    }

    let result = timeout(Duration::from_secs(10), result_rx)
        .await
        .expect("decided result within timeout")
        .expect("result delivered");

    ct.cancel();
    for d in drivers {
        d.abort();
    }
    for t in prioritise_tasks {
        t.abort();
    }

    result
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn cases() {
    let suite = load_suite("priority_scoring");
    let cases = suite["cases"].as_array().expect("cases array");
    let mut failures = Vec::new();

    for case in cases {
        let name = case["name"].as_str().expect("case name");
        let input = &case["input"];
        let topic = input["topic"].as_str().expect("topic");

        let expected: Vec<(String, i64)> = case["result"]
            .as_array()
            .expect("result array")
            .iter()
            .map(|r| {
                (
                    r["priority"].as_str().expect("priority string").to_owned(),
                    r["score"].as_i64().expect("score"),
                )
            })
            .collect();

        let result = run_case(input).await;

        let topic_results: Vec<TopicResult> = result
            .topics
            .iter()
            .map(|t| TopicResult::try_from(t).expect("decode topic result"))
            .collect();
        let Some(versions) = topic_results.iter().find(|t| t.topic == topic) else {
            failures.push(format!(
                "priority_scoring/{name}: topic {topic:?} absent from decided result entirely"
            ));
            continue;
        };
        let actual: Vec<(String, i64)> = versions
            .priorities
            .iter()
            .map(|p| (p.priority.clone(), p.score))
            .collect();

        if actual != expected {
            failures.push(format!(
                "priority_scoring/{name}: got {actual:?}, want {expected:?}"
            ));
        }
    }

    assert_eq!(cases.len(), 18, "expected 18 priority_scoring cases");
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Ladder entry "Preferred priority protocol ID `/charon/priority/2.0.0`" is
/// unreleased (`first_charon_release: null`). At the charon-v1.7.1 parity
/// anchor pluto must serve exactly the legacy slash-less ID. When pluto adds
/// the preferred ID, this test fails: flip it to assert both IDs, slash form
/// preferred, per `priority.md`.
#[test]
fn priority_protocol_ids() {
    assert_eq!(pluto_priority::PROTOCOL_ID, "charon/priority/2.0.0");
    assert_eq!(pluto_priority::protocols(), vec!["charon/priority/2.0.0"]);
}
