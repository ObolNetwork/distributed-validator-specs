//! Guards against a published vector suite that nothing runs.
//!
//! An uncovered suite is indistinguishable from a passing one: the Go consumer's
//! `TestEverySuiteIsCovered` (`consumers/go/testutil/specvectors/specvectors.go`)
//! catches this for Charon; this is the equivalent for the Rust side.

use std::collections::BTreeSet;

/// Suite name -> test file that runs it. Update when a suite or test is added.
const COVERED: &[(&str, &str)] = &[
    ("secp256k1_signatures", "tests/secp256k1_signatures.rs"),
    ("qbft_hashing", "tests/qbft_hashing.rs"),
    ("bls_threshold", "tests/bls_threshold.rs"),
    ("cluster_hashing", "tests/cluster_hashing.rs"),
    ("priority_scoring", "tests/priority_scoring.rs"),
    ("timer_deadlines", "tests/timer_deadlines.rs"),
    ("qbft_msg_limits", "tests/qbft_msg_limits.rs"),
    ("qbft_decided_resends", "tests/qbft_decided_resends.rs"),
    (
        "parsigex_sender_binding",
        "tests/parsigex_sender_binding.rs",
    ),
];

#[test]
fn every_suite_is_covered() {
    let published: BTreeSet<String> = std::fs::read_dir(spec_vectors_pluto::vectors_dir())
        .expect("vectors dir")
        .filter_map(|e| {
            let p = e.expect("dir entry").path();
            (p.extension()? == "json")
                .then(|| p.file_stem().unwrap().to_string_lossy().into_owned())
        })
        .collect();
    let covered: BTreeSet<String> = COVERED.iter().map(|(s, _)| s.to_string()).collect();
    assert_eq!(
        published, covered,
        "published suites and covered suites disagree -- a suite nothing runs is a document, not a test"
    );
    for (suite, file) in COVERED {
        assert!(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join(file)
                .exists(),
            "{suite}: declared test file {file} does not exist"
        );
    }
}
