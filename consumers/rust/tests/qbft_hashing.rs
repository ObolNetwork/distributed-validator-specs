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

#[test]
fn unsigned_data_set_hashing() {
    let suite = load_suite("qbft_hashing");
    let mut failures = Vec::new();
    for case in suite["unsigned_data_set"].as_array().unwrap() {
        let name = format!(
            "qbft_hashing/unsigned_data_set/{}",
            case["name"].as_str().unwrap()
        );
        // Map keys are the literal strings from the vector (e.g. "0xaabb"),
        // not hex-decoded; only values are hex-encoded bytes. pluto's set is
        // BTreeMap<String, Bytes>, whose key ordering gives the deterministic
        // encoding regardless of the vector's insertion order.
        let set = case["input"]["set"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), unhex(v.as_str().unwrap()).into()))
            .collect();
        let uds = UnsignedDataSet { set };
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
