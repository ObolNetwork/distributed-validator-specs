//! Runs the `parsigex_sender_binding` suite against pluto's `dkg`/`parsigex`
//! crates.
//!
//! The vectors are transcribed from charon's `dkg/exchanger_internal_test.go`
//! (`TestVerifyPeerShareIdx` for the `cases` group, and
//! `TestNewExchangerRejectsIncompletePeerMap` for `peer_map`): a peer may only
//! contribute a partial signature under the share index the cluster assigned
//! it, resolved through a peer map rather than the peer's position.
//!
//! **Probe summary (see the report for the full write-up):**
//! - `crates/dkg/src/exchanger.rs`'s `Exchanger` is the structural
//!   counterpart of charon's lock-hash exchanger, but it never validates a
//!   share index at all: `Exchanger::new` takes `peers: Vec<PeerId>` (a bare
//!   list, no index map) and only uses `peers.len()` as an exchange
//!   threshold. Both share-index checking and DKG's peer-map construction
//!   live elsewhere -- and every place they do is unreachable from an
//!   external crate (see the `peer_map` test below for citations).
//! - `crates/dkg/src/aggregate.rs::agg_lock_hash_sig`/`verify_threshold_partials`
//!   *do* look up a partial signature's `share_idx` in a `Share`'s
//!   `public_shares` map and BLS-verify it -- structurally the closest
//!   "verify a claimed share index" code in the whole crate -- but
//!   `crates/dkg/src/lib.rs` declares `mod aggregate;` (no `pub`), so this
//!   function is not reachable either.
//! - The one reachable share-index verifier is
//!   `pluto_parsigex::new_eth2_verifier` (`crates/parsigex/src/lib.rs`
//!   re-exports it from `behaviour.rs`), used in production for ongoing
//!   validator-duty signing (attestations, etc.), not DKG's lock-hash round
//!   (DKG wires parsigex with a no-op verifier and checks signatures itself
//!   in the now-unreachable `aggregate.rs`, per `exchanger.rs`'s "verify
//!   before we aggregate" comment). It is nonetheless pluto's closest
//!   reachable equivalent of the rule under test: it also looks up
//!   `pub_shares_by_key[pubkey][share_idx]` and BLS-verifies. Its `Verifier`
//!   closure type is `Fn(Duty, PubKey, ParSignedData) -> VerifyFuture` --
//!   **it has no sender/peer-identity parameter at all**, confirmed by
//!   reading `new_eth2_verifier` (`crates/parsigex/src/behaviour.rs`) and its
//!   only caller (`crates/parsigex/src/handler.rs`) in full.
//!
//! **`cases` group -- ABSENT-OK.** Ladder entry "Sender-bound share indices
//! in the DKG lock-hash exchange" (`first_charon_release: null`, so no
//! released charon carries it either at pluto's v1.7.1 anchor) covers this
//! gap. Because `new_eth2_verifier`'s closure never receives a sender
//! identity, its accept/reject decision reduces entirely to: is `share_idx` a
//! key in `pub_shares_by_key[pubkey]`, and does the presented signature
//! verify under that key's pubshare. There is no way to even pose "the
//! sender is not the assigned owner of this index" as a question to this
//! API. Each case below is driven for real (`BeaconMock` for eth2-domain
//! resolution, a genuine BLS signature over the resolved signing root) rather
//! than asserting a re-implementation of the rule.
//!
//! **`peer_map` group -- UNREACHABLE.** This predates charon v1.7.1 (no
//! ladder entry excuses it), but every builder of a peer/share-index map is
//! either purely position-derived (so it cannot even represent the vectors'
//! non-contiguous assignment) or a private/`pub(crate)` item with no external
//! entry point. See the dedicated test below for the four citations.

use std::collections::HashMap;

use pluto_core::eth2signeddata::Eth2SignedData;
use pluto_core::signeddata::SignedVoluntaryExit as CoreSignedVoluntaryExit;
use pluto_core::types::{Duty, ParSignedData, PubKey, SignedData, SlotNumber};
use pluto_crypto::blst_impl::BlstImpl;
use pluto_crypto::tbls::Tbls;
use pluto_crypto::types::{PrivateKey, PublicKey};
use pluto_eth2api::spec::phase0;
use pluto_eth2util::signing;
use pluto_parsigex::{VerifyError, new_eth2_verifier};
use pluto_testutil::BeaconMock;
use spec_vectors_pluto::load_suite;

/// Real BLS keypair for one participant's share, used both to populate
/// `pub_shares_by_key` and to produce a genuinely valid signature for that
/// share index when a case calls for one.
struct ShareKey {
    secret: PrivateKey,
    public: PublicKey,
}

impl ShareKey {
    fn generate() -> Self {
        let tbls = BlstImpl;
        let secret = tbls
            .generate_secret_key(rand::thread_rng())
            .expect("secret generation should succeed");
        let public = tbls
            .secret_to_public_key(&secret)
            .expect("public key derivation should succeed");
        Self { secret, public }
    }
}

/// Builds a `SignedVoluntaryExit` genuinely signed with `secret`, resolving
/// the signing domain/root against the real (mocked) beacon-node client --
/// mirrors `pluto_core::eth2signeddata`'s own `assert_verifies` test helper
/// (`crates/core/src/eth2signeddata.rs`), which is the only place in pluto
/// that exercises this signing path end-to-end.
async fn sign_exit(
    client: &pluto_eth2api::EthBeaconNodeApiClient,
    secret: &PrivateKey,
) -> CoreSignedVoluntaryExit {
    let unsigned = CoreSignedVoluntaryExit::new(phase0::SignedVoluntaryExit {
        message: phase0::VoluntaryExit {
            epoch: 5,
            validator_index: 7,
        },
        signature: [0u8; 96],
    });

    let epoch = unsigned.epoch(client).await.expect("epoch resolution");
    let root = unsigned.message_root().expect("message root");
    let sig_root = signing::get_data_root(client, unsigned.domain_name(), epoch, root)
        .await
        .expect("signing-domain data root");
    let sig = BlstImpl.sign(secret, &sig_root).expect("BLS sign");

    unsigned.set_signature(sig).expect("set_signature")
}

/// Drives one `cases` vector entry through the real `new_eth2_verifier`.
///
/// The vector's `sender`/`share_idx_by_peer` fields describe a rule pluto's
/// API cannot even represent (no sender parameter exists), so this always
/// signs the exit with whichever real secret key corresponds to the *claimed*
/// `share_idx` -- i.e. it assumes the message genuinely was produced with
/// that share's private key, isolating "does the binding fire" from "is this
/// forged crypto" (a forged signature would fail for an unrelated reason:
/// `VerifyError::InvalidSignature`, not the absent-binding gap this suite
/// pins). When `share_idx` is not one of the two registered indices (1, 4),
/// there is no real key for it, so an arbitrary throwaway key is used --
/// irrelevant, since the map lookup rejects before any signature is checked.
async fn run_case(
    client: &pluto_eth2api::EthBeaconNodeApiClient,
    pub_shares_by_key: &HashMap<PubKey, HashMap<u64, PublicKey>>,
    self_key: &ShareKey,
    other_key: &ShareKey,
    dv_pubkey: PubKey,
    share_idx: u64,
) -> Result<(), VerifyError> {
    let secret = match share_idx {
        1 => &self_key.secret,
        4 => &other_key.secret,
        _ => &ShareKey::generate().secret,
    };
    let signed = sign_exit(client, secret).await;
    let duty = Duty::new_signature_duty(SlotNumber::new(101));
    let par_signed = ParSignedData::new(signed, share_idx);
    let verifier = new_eth2_verifier(client.clone(), pub_shares_by_key.clone());
    verifier(duty, dv_pubkey, par_signed).await
}

#[tokio::test]
async fn cases() {
    let suite = load_suite("parsigex_sender_binding");
    let cases = suite["cases"].as_array().unwrap();
    assert_eq!(
        cases.len(),
        6,
        "expected 6 parsigex_sender_binding/cases cases"
    );

    let mock = BeaconMock::builder()
        .build()
        .await
        .expect("beacon mock should start");
    let client = mock.client();

    let self_key = ShareKey::generate();
    let other_key = ShareKey::generate();
    let dv_pubkey = PubKey::new([0x42; 48]);
    let pub_shares_by_key: HashMap<PubKey, HashMap<u64, PublicKey>> = HashMap::from([(
        dv_pubkey,
        HashMap::from([(1u64, self_key.public), (4u64, other_key.public)]),
    )]);

    let mut pin_failures = Vec::new();
    let mut report = String::new();

    for case in cases {
        let name = case["name"].as_str().unwrap();
        let input = &case["input"];
        let share_idx = input["share_idx"].as_u64().unwrap();
        let spec_accepted = case["accepted"].as_bool().unwrap();
        let spec_reason = case["reason"].as_str();

        // Sanity-check the vector's own shape: it always describes the same
        // two-peer map with self=1, other=4 -- if a future vector regen
        // changes this, the fixture above (built once, outside the loop)
        // would silently stop matching the case, so fail loudly instead.
        let share_idx_by_peer = &input["share_idx_by_peer"];
        assert_eq!(share_idx_by_peer["self"].as_u64(), Some(1));
        assert_eq!(share_idx_by_peer["other"].as_u64(), Some(4));

        let result = run_case(
            client,
            &pub_shares_by_key,
            &self_key,
            &other_key,
            dv_pubkey,
            share_idx,
        )
        .await;

        // Pin reading: pluto's real, current behaviour. The verifier has no
        // sender parameter, so acceptance depends solely on whether
        // `share_idx` is a registered key (1 or 4) -- exactly what this
        // fixture signs a genuinely valid signature for. This must hold
        // regardless of what the vector's `sender`/`accepted` fields say;
        // if it ever stops holding, either pluto grew a sender check (in
        // which case this whole pin should be revisited and likely deleted)
        // or the fixture/vector shape changed underneath this test.
        let registered = matches!(share_idx, 1 | 4);
        let pluto_accepted = result.is_ok();
        if pluto_accepted != registered {
            pin_failures.push(format!(
                "parsigex_sender_binding/cases/{name}: expected pluto to \
                 {}(share_idx={share_idx} is{} registered), got {result:?}",
                if registered { "accept " } else { "reject " },
                if registered { "" } else { " not" }
            ));
        }
        // Where pluto rejects, the only reason its API can produce here is
        // an unregistered share index -- assert the exact variant so a
        // change in error shape (e.g. pluto starting to distinguish a
        // signature failure) is visible.
        if !registered {
            match &result {
                Err(VerifyError::InvalidShareIndex) => {}
                other => pin_failures.push(format!(
                    "parsigex_sender_binding/cases/{name}: expected \
                     VerifyError::InvalidShareIndex for an unregistered share_idx, got {other:?}"
                )),
            }
        }

        // Spec reading: reported, not asserted. Pluto's `pub_shares_by_key`
        // lookup has no concept of "sender", so it cannot reproduce charon's
        // sender-bound rejections -- diverges exactly on the two cases where
        // the claimed index is registered to *some* peer but the vector's
        // `sender` is not that peer (`another_peers_share_index_rejected`)
        // or is not a peer at all (`unknown_sender_rejected`).
        if pluto_accepted == spec_accepted {
            report.push_str(&format!(
                "parsigex_sender_binding/cases/{name}: matches spec (accepted={spec_accepted})\n"
            ));
        } else {
            report.push_str(&format!(
                "parsigex_sender_binding/cases/{name}: diverges from spec (spec accepted=\
                 {spec_accepted}, reason={spec_reason:?}; pluto accepted={pluto_accepted}) -- \
                 ABSENT-OK, ladder entry \"Sender-bound share indices in the DKG lock-hash \
                 exchange\" (first_charon_release: null): new_eth2_verifier has no sender \
                 parameter, so it cannot enforce which peer may claim which share index\n"
            ));
        }
    }

    println!("{report}");
    assert!(pin_failures.is_empty(), "{}", pin_failures.join("\n"));
}

/// `peer_map` group -- construction-time validation of a peer/share-index
/// map. UNREACHABLE: every function in pluto that builds or validates such a
/// map is either arithmetically incapable of representing the vectors'
/// non-contiguous assignment, or private/`pub(crate)`.
///
/// Citations (file + function, no line numbers per the report contract):
/// - `crates/p2p/src/peer.rs::Peer::share_idx` / `crates/cluster/src/
///   definition.rs::Definition::node_idx` (both `pub`, reachable) -- but
///   `share_idx` is defined as `self.index.wrapping_add(1)`, i.e. purely the
///   operator's position in the definition's peer list. There is no `pub`
///   path that can produce share index 4 for the second of two peers (this
///   suite's `share_idx_by_peer = {self: 1, other: 4}`): the API has no
///   parameter through which to supply an assigned index at all, so it
///   cannot even be driven with these inputs, let alone tested for
///   accepting/rejecting them.
/// - `crates/dkg/src/node.rs::setup_p2p` -- builds a real `share_idx_by_peer:
///   HashMap<PeerId, u32>` (again from `peer.share_idx()`, so
///   position-derived) before constructing the FROST P2P transport, but is
///   `pub(crate) async fn`; `crates/dkg/src/lib.rs` declares `mod node;`
///   (private), so this function is unreachable from an external crate.
/// - `crates/dkg/src/frostp2p/transport.rs::validate_peer_share_indices` --
///   the one function that actually validates a map (rejects `share_idx ==
///   0`, duplicate indices, and a map missing the local peer's index) has no
///   visibility modifier at all (private to its module); its only caller,
///   `new_frost_p2p`, is `pub(crate)`; and `crates/dkg/src/lib.rs` declares
///   `mod frostp2p;` (private) -- three layers of unreachability.
/// - `crates/app/src/node/mod.rs::build_pub_shares_by_key` -- builds
///   `pub_shares_by_key` for `new_eth2_verifier` from a `Lock`, but is a
///   private `fn` (no `pub`), and is itself position-derived
///   (`(pos as u64).saturating_add(1)`), so it has the same representational
///   gap as `Definition::node_idx` even where it is compiled from a
///   `pub`-reachable crate.
///
/// Each case is still enumerated and its shape asserted below, per the task
/// brief's "cases must still be enumerated and accounted for" requirement --
/// there is simply no reachable pluto API left to call with its inputs.
#[test]
fn peer_map() {
    let suite = load_suite("parsigex_sender_binding");
    let cases = suite["peer_map"].as_array().unwrap();
    assert_eq!(
        cases.len(),
        3,
        "expected 3 parsigex_sender_binding/peer_map cases"
    );

    let mut accounted = Vec::new();
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let input = &case["input"];
        let peers: Vec<&str> = input["peers"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| p.as_str().unwrap())
            .collect();
        let share_idx_by_peer: HashMap<&str, u64> = input["share_idx_by_peer"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_u64().unwrap()))
            .collect();
        let peer_idx = input["peer_idx"].as_u64().unwrap();
        let accepted = case["accepted"].as_bool().unwrap();
        let reason = case["reason"].as_str();

        // Confirm the very thing that makes this UNREACHABLE rather than a
        // reachable PASS/FAIL: at least one peer in every case's roster has
        // no map entry, or the map assigns index 0, or the map is
        // non-contiguous (index 4 for a 2-peer map) -- none of which
        // `Peer::share_idx`'s position-derived formula (`position + 1`) can
        // even receive as input, since it has no map parameter at all.
        let all_positional = peers
            .iter()
            .enumerate()
            .all(|(i, peer)| share_idx_by_peer.get(peer) == Some(&(i as u64 + 1)));
        assert!(
            !all_positional || share_idx_by_peer.len() != peers.len(),
            "parsigex_sender_binding/peer_map/{name}: this case's map is fully \
             position-derived, so it no longer demonstrates non-reachability -- \
             re-check whether a public position-derived builder now applies"
        );

        accounted.push(format!(
            "parsigex_sender_binding/peer_map/{name}: UNREACHABLE (spec expects \
             accepted={accepted}, reason={reason:?}, for peers={peers:?} peer_idx={peer_idx}) -- \
             no reachable pluto construction validates a peer/share-index map; see the module \
             doc comment for the four citations"
        ));
    }

    assert_eq!(accounted.len(), 3);
    println!("{}", accounted.join("\n"));
}
