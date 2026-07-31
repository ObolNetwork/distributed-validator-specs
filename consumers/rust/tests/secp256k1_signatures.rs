use spec_vectors_pluto::{load_suite, unhex};

#[test]
fn secp256k1_signatures() {
    let suite = load_suite("secp256k1_signatures");
    let secret = k256::SecretKey::from_slice(&unhex(suite["secret_hex"].as_str().unwrap()))
        .expect("suite secret key");
    let pubkey = secret.public_key();
    let mut failures = Vec::new();

    for case in suite["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let hash = unhex(case["input"]["hash_hex"].as_str().unwrap());
        let want_sig = unhex(case["signature_hex"].as_str().unwrap());
        let want_pub = unhex(case["recovered_pubkey_hex"].as_str().unwrap());

        match pluto_k1util::sign(&secret, &hash) {
            Ok(sig) if sig.to_vec() == want_sig => {}
            Ok(sig) => failures.push(format!(
                "{name}: sign gave {}, want {}",
                hex::encode(sig),
                hex::encode(&want_sig)
            )),
            Err(e) => failures.push(format!("{name}: sign failed: {e}")),
        }
        match pluto_k1util::recover(&hash, &want_sig) {
            Ok(rec) if rec.to_sec1_bytes().to_vec() == want_pub => {}
            Ok(rec) => failures.push(format!(
                "{name}: recover gave {}, want {}",
                hex::encode(rec.to_sec1_bytes()),
                hex::encode(&want_pub)
            )),
            Err(e) => failures.push(format!("{name}: recover failed: {e}")),
        }
        match pluto_k1util::verify_65(&pubkey, &hash, &want_sig) {
            Ok(true) => {}
            other => failures.push(format!("{name}: verify_65 gave {other:?}, want Ok(true)")),
        }
    }
    assert!(
        failures.is_empty(),
        "{} failures:\n{}",
        failures.len(),
        failures.join("\n")
    );
}
