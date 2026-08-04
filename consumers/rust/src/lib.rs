//! Loader for the spec's test_vectors/ suites.
//!
//! Vectors are read from `../../test_vectors/` relative to this package, or from
//! `SPEC_VECTORS_DIR` when set. `load_suite` refuses a file whose `suite` field
//! does not match the requested name, so a stray copy cannot silently substitute.

use std::path::PathBuf;

pub fn vectors_dir() -> PathBuf {
    match std::env::var_os("SPEC_VECTORS_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../test_vectors"),
    }
}

pub fn load_suite(name: &str) -> serde_json::Value {
    let path = vectors_dir().join(format!("{name}.json"));
    let raw =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let suite: serde_json::Value =
        serde_json::from_str(&raw).unwrap_or_else(|e| panic!("parse {}: {e}", path.display()));
    assert_eq!(
        suite["suite"],
        name,
        "suite field mismatch in {}",
        path.display()
    );
    suite
}

pub fn unhex(s: &str) -> Vec<u8> {
    hex::decode(s).unwrap_or_else(|e| panic!("bad hex {s:?}: {e}"))
}
