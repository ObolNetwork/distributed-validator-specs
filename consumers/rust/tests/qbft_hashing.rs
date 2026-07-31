use prost::Message;
use spec_vectors_pluto::{load_suite, unhex};

use pluto_consensus::qbft::msg::{hash_proto, hash_proto_bytes};
use pluto_core::corepb::v1::{Duty, QbftMsg, UnsignedDataSet};

fn check(
    failures: &mut Vec<String>,
    name: &str,
    encoded: &[u8],
    hash: [u8; 32],
    case: &serde_json::Value,
) {
    let want_enc = unhex(case["encoding_hex"].as_str().unwrap());
    let want_hash = unhex(case["hash_hex"].as_str().unwrap());
    if encoded != want_enc {
        failures.push(format!(
            "{name}: encoding {}, want {}",
            hex::encode(encoded),
            hex::encode(&want_enc)
        ));
    }
    if hash.as_slice() != want_hash {
        failures.push(format!(
            "{name}: hash {}, want {}",
            hex::encode(hash),
            hex::encode(&want_hash)
        ));
    }
}

#[test]
fn duty_hashing() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["duty"].as_array().unwrap() {
        let name = format!("qbft_hashing/duty/{}", case["name"].as_str().unwrap());
        let duty = Duty {
            // Duty.slot is a proto uint64 (generated as Rust u64); the max-slot
            // vector exercises the full u64 range, which as_i64 cannot hold.
            slot: case["input"]["slot"].as_u64().unwrap(),
            r#type: case["input"]["type"].as_i64().unwrap() as i32,
        };
        // Covers the <=32-byte rule: a short encoding is returned zero-padded,
        // unhashed. hash_proto/hash_proto_bytes already implement this; the
        // test only checks the outcome.
        match hash_proto(&duty) {
            Ok(h) => check(&mut failures, &name, &duty.encode_to_vec(), h, case),
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert_eq!(
        suite["duty"].as_array().unwrap().len(),
        3,
        "expected 3 duty cases"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Map keys are the literal strings from the vector (e.g. "0xaabb"), not
/// hex-decoded; only values are hex-encoded bytes. pluto's set is
/// `BTreeMap<String, Bytes>`, whose key ordering gives the deterministic
/// encoding regardless of the vector's insertion order.
fn build_unsigned_data_set(case: &serde_json::Value) -> UnsignedDataSet {
    let set = case["input"]["set"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), unhex(v.as_str().unwrap()).into()))
        .collect();
    UnsignedDataSet { set }
}

/// Cases excluded from the strict check below because pluto's map encoding is
/// known to diverge from charon's on them. See
/// `unsigned_data_set_known_divergence_empty_map_entry_fields` for the
/// recorded FAIL and why only these two are excluded.
const KNOWN_DIVERGENT_UNSIGNED_DATA_SET_CASES: &[&str] = &["empty_value", "empty_key"];

#[test]
fn unsigned_data_set_hashing() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    let mut skipped = Vec::new();
    for case in suite["unsigned_data_set"].as_array().unwrap() {
        let case_name = case["name"].as_str().unwrap();
        if KNOWN_DIVERGENT_UNSIGNED_DATA_SET_CASES.contains(&case_name) {
            skipped.push(case_name.to_string());
            continue;
        }
        let name = format!("qbft_hashing/unsigned_data_set/{case_name}");
        let uds = build_unsigned_data_set(case);
        match hash_proto(&uds) {
            Ok(h) => check(&mut failures, &name, &uds.encode_to_vec(), h, case),
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert_eq!(
        suite["unsigned_data_set"].as_array().unwrap().len(),
        12,
        "expected 12 unsigned_data_set cases"
    );
    // This checks only that the vector still contains cases named exactly
    // these two strings, so a renamed or removed known-divergent case fails
    // loudly instead of silently vanishing from the strict check below. It
    // cannot detect whether the named cases still actually diverge — that is
    // unsigned_data_set_known_divergence_empty_map_entry_fields's job: its
    // "still differs from the vector" assertion goes red if pluto's output
    // ever starts matching the spec.
    let mut skipped_sorted = skipped.clone();
    skipped_sorted.sort_unstable();
    let mut want_sorted: Vec<String> = KNOWN_DIVERGENT_UNSIGNED_DATA_SET_CASES
        .iter()
        .map(|s| s.to_string())
        .collect();
    want_sorted.sort_unstable();
    assert_eq!(
        skipped_sorted, want_sorted,
        "the set of cases skipped as known-divergent changed; a case may have started or \
         stopped diverging — see unsigned_data_set_known_divergence_empty_map_entry_fields"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Known FAIL, recorded in `plans/pluto-conformance.md` under Findings: pluto's
/// map encoding (prost's generated `btree_map` codec) applies proto3
/// default-value omission *inside* a map entry, skipping the key field when it
/// equals `""` and the value field when it equals `b""`
/// (prost-0.14.4 `src/encoding.rs:1044-1059`, `encode_with_default`). Charon's
/// `hashProto`, built on Go's `google.golang.org/protobuf`, always writes both
/// map-entry fields, default-valued or not. Charon's encoding is correct per
/// spec; pluto's is wrong. This is deliberately not treated as ABSENT-OK: no
/// `charon_anchor.json` ladder entry documents a map-entry-presence gap, so
/// this is pluto being wrong, not pluto legitimately trailing a dated charon
/// release.
///
/// This test pins pluto's *current* (wrong) output byte-for-byte, and
/// separately asserts that output still differs from the vector's expected
/// bytes. Consequence: if pluto ever fixes its map encoding to match charon's
/// explicit-presence behaviour, the "still differs from the vector"
/// assertion below fails — that failure is the signal to delete this test and
/// move `empty_value`/`empty_key` into `unsigned_data_set_hashing`'s strict
/// checks (and out of `KNOWN_DIVERGENT_UNSIGNED_DATA_SET_CASES` there). If
/// pluto's output instead changes to a *different* wrong value, the "pinned"
/// assertion below fails, surfacing that regression too rather than hiding it
/// behind an already-red case.
#[test]
fn unsigned_data_set_known_divergence_empty_map_entry_fields() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    // (case name, pluto's current encoding, pluto's current hash), captured
    // from a real run against the pluto commit under test.
    let pinned: &[(&str, &str, &str)] = &[
        (
            "empty_value",
            "0a080a06307861616262",
            "0a080a0630786161626200000000000000000000000000000000000000000000",
        ),
        (
            "empty_key",
            "0a03120101",
            "0a03120101000000000000000000000000000000000000000000000000000000",
        ),
    ];
    let mut seen = Vec::new();
    for case in suite["unsigned_data_set"].as_array().unwrap() {
        let case_name = case["name"].as_str().unwrap();
        let Some(&(_, pinned_enc, pinned_hash)) =
            pinned.iter().find(|(name, _, _)| *name == case_name)
        else {
            continue;
        };
        seen.push(case_name.to_string());
        let name = format!("qbft_hashing/unsigned_data_set/{case_name}");
        let uds = build_unsigned_data_set(case);
        let encoded = uds.encode_to_vec();
        let want_enc = unhex(case["encoding_hex"].as_str().unwrap());
        let pinned_enc_bytes = unhex(pinned_enc);
        if encoded != pinned_enc_bytes {
            failures.push(format!(
                "{name}: pluto's encoding moved from the pinned divergence {} to {} — \
                 investigate before assuming this is the known fix",
                hex::encode(&pinned_enc_bytes),
                hex::encode(&encoded)
            ));
        }
        if encoded == want_enc {
            failures.push(format!(
                "{name}: pluto's encoding now matches the vector — promote this case into \
                 unsigned_data_set_hashing and remove it from \
                 KNOWN_DIVERGENT_UNSIGNED_DATA_SET_CASES"
            ));
        }
        match hash_proto(&uds) {
            Ok(h) => {
                let pinned_hash_bytes = unhex(pinned_hash);
                let want_hash = unhex(case["hash_hex"].as_str().unwrap());
                if h.as_slice() != pinned_hash_bytes {
                    failures.push(format!(
                        "{name}: pluto's hash moved from the pinned divergence {} to {} — \
                         investigate before assuming this is the known fix",
                        hex::encode(pinned_hash_bytes),
                        hex::encode(h)
                    ));
                }
                if h.as_slice() == want_hash {
                    failures.push(format!(
                        "{name}: pluto's hash now matches the vector — promote this case into \
                         unsigned_data_set_hashing and remove it from \
                         KNOWN_DIVERGENT_UNSIGNED_DATA_SET_CASES"
                    ));
                }
            }
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert_eq!(
        seen.len(),
        pinned.len(),
        "expected to find both known-divergent cases in the vector file"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn qbft_signing_roots() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["qbft_signing_root"].as_array().unwrap() {
        let name = format!(
            "qbft_hashing/qbft_signing_root/{}",
            case["name"].as_str().unwrap()
        );
        let i = &case["input"];
        // value_hash / prepared_value_hash are always 32 bytes on the wire,
        // zeros meaning "no value". The signing root is computed with the
        // signature field cleared (mirrors pluto's own sign_msg), which is why
        // "attester_pre_prepare" and "attester_pre_prepare_signed" share a
        // root despite the vector carrying a non-empty input.signature.
        let msg = QbftMsg {
            r#type: i["type"].as_i64().unwrap(),
            duty: Some(Duty {
                slot: i["slot"].as_u64().unwrap(),
                r#type: i["duty_type"].as_i64().unwrap() as i32,
            }),
            peer_idx: i["peer_idx"].as_i64().unwrap(),
            round: i["round"].as_i64().unwrap(),
            prepared_round: i["prepared_round"].as_i64().unwrap(),
            value_hash: unhex(i["value_hash"].as_str().unwrap()).into(),
            prepared_value_hash: unhex(i["prepared_value_hash"].as_str().unwrap()).into(),
            signature: Default::default(),
        };
        match hash_proto(&msg) {
            Ok(h) => check(&mut failures, &name, &msg.encode_to_vec(), h, case),
            Err(e) => failures.push(format!("{name}: hash_proto failed: {e}")),
        }
    }
    assert_eq!(
        suite["qbft_signing_root"].as_array().unwrap().len(),
        6,
        "expected 6 qbft_signing_root cases"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn any_string_hashing() {
    // Charon's *priority* hashProto hashes the Any wrapper itself, type URL
    // included, while pluto's hash_proto rejects Any outright (the consensus
    // hasher must bind to inner message bytes). hash_proto_bytes over the
    // encoded Any exercises the same merkleization path pluto's priority
    // component uses via hash_any (crates/priority/src/calculate.rs).
    //
    // The vector's type URL decodes to "google.protobuf.Value" with the
    // string carried in the oneof's string_value (field 3), not
    // "google.protobuf.StringValue" field 1 — confirmed by decoding
    // encoding_hex before writing this construction.
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["any_string"].as_array().unwrap() {
        let name = format!("qbft_hashing/any_string/{}", case["name"].as_str().unwrap());
        let s = case["input"]["string_value"].as_str().unwrap();
        let value = prost_types::Value {
            kind: Some(prost_types::value::Kind::StringValue(s.to_string())),
        };
        // prost_types::Value has no Name impl in this prost-types version, so
        // Any::from_msg is unavailable; build the envelope directly.
        let any = prost_types::Any {
            type_url: "type.googleapis.com/google.protobuf.Value".into(),
            value: value.encode_to_vec(),
        };
        let encoded = any.encode_to_vec();
        match hash_proto_bytes(&encoded) {
            Ok(h) => check(&mut failures, &name, &encoded, h, case),
            Err(e) => failures.push(format!("{name}: hash_proto_bytes failed: {e}")),
        }
    }
    assert_eq!(
        suite["any_string"].as_array().unwrap().len(),
        4,
        "expected 4 any_string cases"
    );
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
