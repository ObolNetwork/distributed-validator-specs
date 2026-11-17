//! Runs the `cluster_validation` suite against pluto's `cluster` crate.
//!
//! **Status: ABSENT-OK for rejections.** The suite pins rules this spec added
//! after charon's anchor (fixed-length fields rejected rather than padded,
//! EIP-55 checksums, zero addresses on mainnet and Gnosis, lock deposit data
//! and registrations checked against the definition). No charon release
//! enforces them at load, and pluto at its v1.7.1 anchor does not either, so a
//! rejected case that pluto accepts is reported, not failed. The accepted cases
//! are asserted strictly: a reader must not reject a valid file.
//!
//! Only parsing and `verify_hashes` are exercised. Pluto's
//! `verify_signatures` needs an `EthClient`; the lock cases are unsigned
//! definitions, so wiring one is the next step to cover the deposit and
//! registration rules. Not compiled in this repository (see
//! `tests/test_consumers.py`); written against the same pluto API as
//! `cluster_hashing.rs`.

use pluto_cluster::definition::Definition;
use pluto_cluster::lock::Lock;
use spec_vectors_pluto::load_suite;

fn definition_verdict(input: &serde_json::Value) -> Result<(), String> {
    let def: Definition = serde_json::from_value(input.clone()).map_err(|e| format!("parse: {e}"))?;
    def.verify_hashes().map_err(|e| format!("verify_hashes: {e}"))
}

fn lock_verdict(input: &serde_json::Value) -> Result<(), String> {
    let lock: Lock = serde_json::from_value(input.clone()).map_err(|e| format!("parse: {e}"))?;
    lock.verify_hashes().map_err(|e| format!("verify_hashes: {e}"))
}

fn run(group: &str, expected_cases: usize, verdict: fn(&serde_json::Value) -> Result<(), String>) {
    let suite = load_suite("cluster_validation");
    let cases = suite[group].as_array().unwrap();
    assert_eq!(cases.len(), expected_cases, "unexpected number of {group} cases");

    let mut failures = Vec::new();
    let mut absent = Vec::new();
    for case in cases {
        let name = format!("cluster_validation/{group}/{}", case["name"].as_str().unwrap());
        let accepted = case["accepted"].as_bool().unwrap();

        match (accepted, verdict(&case["input"])) {
            (true, Err(e)) => failures.push(format!("{name}: must accept: {e}")),
            (false, Ok(())) => absent.push(format!(
                "{name}: accepted, spec rejects with {}",
                case["reason"].as_str().unwrap()
            )),
            _ => {}
        }
    }

    for line in &absent {
        eprintln!("ABSENT-OK {line}");
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn definition_validation() {
    run("definition", 23, definition_verdict);
}

#[test]
fn lock_validation() {
    run("lock", 26, lock_verdict);
}
