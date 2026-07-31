use std::collections::HashMap;

use pluto_crypto::blst_impl::BlstImpl;
use pluto_crypto::tbls::Tbls;
use spec_vectors_pluto::{load_suite, unhex};

fn arr<const N: usize>(v: &[u8]) -> [u8; N] {
    v.try_into().expect("length")
}

/// `share_idx` in the vector's `partials` group is 1-based, matching
/// `pluto_crypto`'s `Index` convention; no conversion is needed.
fn share_secrets(suite: &serde_json::Value) -> HashMap<u64, [u8; 32]> {
    suite["partials"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| {
            let idx = p["input"]["share_idx"].as_u64().unwrap();
            let secret: [u8; 32] = arr(&unhex(p["input"]["secret_hex"].as_str().unwrap()));
            (idx, secret)
        })
        .collect()
}

fn share_partial_signatures(suite: &serde_json::Value) -> HashMap<u64, [u8; 96]> {
    suite["partials"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| {
            let idx = p["input"]["share_idx"].as_u64().unwrap();
            let sig: [u8; 96] = arr(&unhex(p["signature_hex"].as_str().unwrap()));
            (idx, sig)
        })
        .collect()
}

#[test]
fn keys() {
    let suite = load_suite("bls_threshold");
    let t = BlstImpl;
    let mut failures = Vec::new();

    for case in suite["keys"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let secret: [u8; 32] = arr(&unhex(case["input"]["secret_hex"].as_str().unwrap()));
        let want_pub = unhex(case["pubkey_hex"].as_str().unwrap());
        match t.secret_to_public_key(&secret) {
            Ok(pk) if pk.to_vec() == want_pub => {}
            other => failures.push(format!(
                "bls_threshold/keys/{name}: secret_to_public_key gave {other:?}, want {}",
                hex::encode(&want_pub)
            )),
        }
    }
    assert_eq!(
        suite["keys"].as_array().unwrap().len(),
        2,
        "expected 2 keys cases"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn partials() {
    let suite = load_suite("bls_threshold");
    let t = BlstImpl;
    let msg = unhex(suite["message_hex"].as_str().unwrap());
    let mut failures = Vec::new();

    for case in suite["partials"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let secret: [u8; 32] = arr(&unhex(case["input"]["secret_hex"].as_str().unwrap()));
        let want_pub = unhex(case["pubshare_hex"].as_str().unwrap());
        let want_sig = unhex(case["signature_hex"].as_str().unwrap());

        match t.secret_to_public_key(&secret) {
            Ok(pk) if pk.to_vec() == want_pub => {}
            other => failures.push(format!(
                "bls_threshold/partials/{name}: pubshare gave {other:?}, want {}",
                hex::encode(&want_pub)
            )),
        }
        match t.sign(&secret, &msg) {
            Ok(sig) if sig.to_vec() == want_sig => {}
            other => failures.push(format!(
                "bls_threshold/partials/{name}: partial signature gave {other:?}, want {}",
                hex::encode(&want_sig)
            )),
        }
    }
    assert_eq!(
        suite["partials"].as_array().unwrap().len(),
        4,
        "expected 4 partials cases"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Each of the four distinct 3-of-4 quorums must reproduce the *same* group
/// signature: this is the point of threshold aggregation (any quorum
/// interpolates the same degree-2 polynomial at x=0), and only checking one
/// quorum would not distinguish correct Lagrange coefficients from a
/// coincidentally well-formed but wrong signature.
#[test]
fn threshold_aggregates() {
    let suite = load_suite("bls_threshold");
    let t = BlstImpl;
    let msg = unhex(suite["message_hex"].as_str().unwrap());
    let group_pub: [u8; 48] = arr(&unhex(suite["group_pubkey_hex"].as_str().unwrap()));
    let group_sig: [u8; 96] = arr(&unhex(suite["group_signature_hex"].as_str().unwrap()));
    let partials = share_partial_signatures(&suite);
    let mut failures = Vec::new();

    if t.verify(&group_pub, &msg, &group_sig).is_err() {
        failures.push(
            "bls_threshold/threshold_aggregates/group_signature_hex: does not verify under \
             group_pubkey_hex"
                .to_string(),
        );
    }

    let mut seen_quorums: Vec<Vec<u64>> = Vec::new();
    for case in suite["threshold_aggregates"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let want: [u8; 96] = arr(&unhex(case["signature_hex"].as_str().unwrap()));
        let mut indices: Vec<u64> = case["input"]["share_indices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| i.as_u64().unwrap())
            .collect();
        let subset: HashMap<u64, [u8; 96]> = indices.iter().map(|i| (*i, partials[i])).collect();

        match t.threshold_aggregate(&subset) {
            Ok(sig) if sig == want && sig == group_sig => {}
            Ok(sig) if sig == want => failures.push(format!(
                "bls_threshold/threshold_aggregates/{name}: matched the vector but not \
                 group_signature_hex, got {}",
                hex::encode(sig)
            )),
            other => failures.push(format!(
                "bls_threshold/threshold_aggregates/{name}: gave {other:?}, want {}",
                hex::encode(want)
            )),
        }

        indices.sort_unstable();
        seen_quorums.push(indices);
    }
    assert_eq!(
        suite["threshold_aggregates"].as_array().unwrap().len(),
        4,
        "expected 4 threshold_aggregates cases"
    );
    let mut unique_quorums = seen_quorums.clone();
    unique_quorums.sort_unstable();
    unique_quorums.dedup();
    assert_eq!(
        unique_quorums.len(),
        seen_quorums.len(),
        "expected 4 distinct quorums, got duplicates: {seen_quorums:?}"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn recovery() {
    let suite = load_suite("bls_threshold");
    let t = BlstImpl;
    let group_pub: [u8; 48] = arr(&unhex(suite["group_pubkey_hex"].as_str().unwrap()));
    let group_secret: [u8; 32] = arr(&unhex(suite["group_secret_hex"].as_str().unwrap()));
    let secrets = share_secrets(&suite);
    let mut failures = Vec::new();

    for case in suite["recovery"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let want_pub = unhex(case["pubkey_hex"].as_str().unwrap());
        let subset: HashMap<u64, [u8; 32]> = case["input"]["share_indices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| {
                let i = i.as_u64().unwrap();
                (i, secrets[&i])
            })
            .collect();

        match t.recover_secret(&subset) {
            Ok(secret) if secret != group_secret => failures.push(format!(
                "bls_threshold/recovery/{name}: recovered secret {}, want the group secret",
                hex::encode(secret)
            )),
            Ok(secret) => match t.secret_to_public_key(&secret) {
                Ok(pk) if pk.to_vec() == want_pub && pk == group_pub => {}
                other => failures.push(format!(
                    "bls_threshold/recovery/{name}: recovered secret's public key gave \
                     {other:?}, want {}",
                    hex::encode(&want_pub)
                )),
            },
            Err(e) => failures.push(format!(
                "bls_threshold/recovery/{name}: recover_secret failed: {e}"
            )),
        }
    }
    assert_eq!(
        suite["recovery"].as_array().unwrap().len(),
        1,
        "expected 1 recovery case"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Plain aggregation (used for the cluster lock hash) is not threshold
/// aggregation: it must reproduce the pinned bytes, and — the whole reason
/// threshold aggregation exists — must NOT verify under the group public key.
#[test]
fn plain_aggregate() {
    let suite = load_suite("bls_threshold");
    let t = BlstImpl;
    let msg = unhex(suite["message_hex"].as_str().unwrap());
    let group_pub: [u8; 48] = arr(&unhex(suite["group_pubkey_hex"].as_str().unwrap()));
    let partials = share_partial_signatures(&suite);
    let mut failures = Vec::new();

    for case in suite["plain_aggregate"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let want: [u8; 96] = arr(&unhex(case["signature_hex"].as_str().unwrap()));
        let sigs: Vec<[u8; 96]> = case["input"]["share_indices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| partials[&i.as_u64().unwrap()])
            .collect();

        match t.aggregate(&sigs) {
            Ok(sig) if sig == want => {
                if t.verify(&group_pub, &msg, &sig).is_ok() {
                    failures.push(format!(
                        "bls_threshold/plain_aggregate/{name}: verified under \
                         group_pubkey_hex, must not"
                    ));
                }
            }
            other => failures.push(format!(
                "bls_threshold/plain_aggregate/{name}: gave {other:?}, want {}",
                hex::encode(want)
            )),
        }
    }
    assert_eq!(
        suite["plain_aggregate"].as_array().unwrap().len(),
        1,
        "expected 1 plain_aggregate case"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
