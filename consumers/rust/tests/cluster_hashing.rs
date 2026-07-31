use pluto_cluster::definition::Definition;
use pluto_cluster::lock::Lock;
use spec_vectors_pluto::load_suite;

/// `all_empty_lists` is a real charon divergence, not a test bug — and it has
/// **at least two independent parse blockers stacked**, so fixing only the
/// first will not make this case pass:
///
/// 1. Charon's `Operators`/`ValidatorAddresses` fields lack `omitempty`
///    (`cluster/definition.go`), so Go's `encoding/json` marshals a nil slice
///    as `null`. Pluto's `DefinitionV1x10.operators`/`.validator_addresses`
///    (`crates/cluster/src/definition.rs`) have no `#[serde(default)]` and
///    reject `null` outright. This is the error this test currently observes.
/// 2. Masked behind (1): charon's `Timestamp` field *does* carry `omitempty`
///    (`definitionJSONv1x10to11`, `cluster/definition.go`), so an empty
///    timestamp is legitimately absent from the JSON. Pluto's
///    `DefinitionV1x10.timestamp` also has no `#[serde(default)]`. Confirmed
///    by mutation: relaxing `operators`/`validators` from `null` to `[]` (as
///    if (1) were fixed) still fails to parse, now on "missing field
///    `timestamp`".
///
/// Whoever sees this test go red after a pluto change should expect to find
/// the *next* blocker, not assume the case now passes end to end — only after
/// (1) and (2) both resolve does `all_empty_lists` belong back in the strict
/// `definition_hashes` loop. See the cluster_hashing Results row / Findings
/// entry for the full field list (a lower bound, not a total — later fields
/// are never reached while an earlier one blocks parsing).
const DEFINITION_KNOWN_DIVERGENCE: &str = "all_empty_lists";

/// `validator_without_deposit_data` is the lock-side counterpart: charon's
/// `PartialDepositData` field carries `omitempty`
/// (`cluster/distvalidator.go`), so Go omits the key entirely for a validator
/// with no partial deposits. Pluto's
/// `DistValidatorV1x8orLater.partial_deposit_data`
/// (`crates/cluster/src/distvalidator.rs`) has no `#[serde(default)]` and
/// requires the key present.
const LOCK_KNOWN_DIVERGENCE: &str = "validator_without_deposit_data";

#[test]
fn definition_hashes() {
    let suite = load_suite("cluster_hashing");
    let cases = suite["definition"].as_array().unwrap();
    assert_eq!(cases.len(), 6, "unexpected number of definition cases");

    let mut failures = Vec::new();
    for case in cases {
        let case_name = case["name"].as_str().unwrap();
        if case_name == DEFINITION_KNOWN_DIVERGENCE {
            continue;
        }
        let name = format!("cluster_hashing/definition/{case_name}");

        let mut def: Definition = match serde_json::from_value(case["input"].clone()) {
            Ok(d) => d,
            Err(e) => {
                failures.push(format!("{name}: parse: {e}"));
                continue;
            }
        };

        if let Err(e) = def.set_definition_hashes() {
            failures.push(format!("{name}: set_definition_hashes: {e}"));
            continue;
        }

        let want_config = case["config_hash"].as_str().unwrap();
        let want_definition = case["definition_hash"].as_str().unwrap();

        let got_config = hex::encode(&def.config_hash);
        if got_config != want_config {
            failures.push(format!(
                "{name}: config_hash {got_config}, want {want_config}"
            ));
        }

        let got_definition = hex::encode(&def.definition_hash);
        if got_definition != want_definition {
            failures.push(format!(
                "{name}: definition_hash {got_definition}, want {want_definition}"
            ));
        }
    }

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Pins the *first* of `all_empty_lists`'s at-least-two parse blockers (see
/// the constant's doc comment): fails loudly (a regression to investigate,
/// not a silent fix) the moment pluto's `Definition` parser starts accepting
/// `operators: null` / `validators: null`. That alone does not make the case
/// parse — the masked `timestamp` blocker still applies — so a green here
/// means "go find the next blocker", not "move this case into the strict
/// `definition_hashes` loop".
#[test]
fn definition_known_divergence_null_operators_and_validators() {
    let suite = load_suite("cluster_hashing");
    let case = suite["definition"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == DEFINITION_KNOWN_DIVERGENCE)
        .expect("all_empty_lists present");

    let err = serde_json::from_value::<Definition>(case["input"].clone())
        .expect_err("expected pluto to still reject null operators/validators");
    assert!(
        err.to_string().contains("null") || err.to_string().contains("sequence"),
        "unexpected error shape, pluto's rejection reason may have changed: {err}"
    );
}

/// The unsigned and signed single-operator cases share a config_hash (signing
/// must not move the config hash) while their definition_hash must differ
/// (signatures are part of the definition hash).
#[test]
fn signing_does_not_move_config_hash() {
    let suite = load_suite("cluster_hashing");
    let cases = suite["definition"].as_array().unwrap();

    let find = |name: &str| -> Definition {
        let case = cases
            .iter()
            .find(|c| c["name"] == name)
            .unwrap_or_else(|| panic!("{name} present"));
        let mut def: Definition = serde_json::from_value(case["input"].clone())
            .unwrap_or_else(|e| panic!("parse {name}: {e}"));
        def.set_definition_hashes()
            .unwrap_or_else(|e| panic!("set_definition_hashes {name}: {e}"));
        def
    };

    let unsigned = find("unsigned_single_operator");
    let signed = find("signed_single_operator");

    assert_eq!(
        unsigned.config_hash, signed.config_hash,
        "config_hash must not move when signatures are added"
    );
    assert_ne!(
        unsigned.definition_hash, signed.definition_hash,
        "definition_hash must move when signatures are added"
    );
}

#[tokio::test]
async fn lock_hashes_and_verification() {
    let suite = load_suite("cluster_hashing");
    let cases = suite["lock"].as_array().unwrap();
    assert_eq!(cases.len(), 4, "unexpected number of lock cases");

    let mut failures = Vec::new();
    for case in cases {
        let case_name = case["name"].as_str().unwrap();
        if case_name == LOCK_KNOWN_DIVERGENCE {
            continue;
        }
        let name = format!("cluster_hashing/lock/{case_name}");

        let mut lock: Lock = match serde_json::from_value(case["input"].clone()) {
            Ok(l) => l,
            Err(e) => {
                failures.push(format!("{name}: parse: {e}"));
                continue;
            }
        };

        if let Err(e) = lock.set_lock_hash() {
            failures.push(format!("{name}: set_lock_hash: {e}"));
            continue;
        }

        let want = case["lock_hash"].as_str().unwrap();
        let got = hex::encode(&lock.lock_hash);
        if got != want {
            failures.push(format!("{name}: lock_hash {got}, want {want}"));
        }

        if let Err(e) = lock.verify_hashes() {
            failures.push(format!("{name}: verify_hashes: {e}"));
        }
    }

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Pins the `validator_without_deposit_data` divergence: fails loudly the
/// moment pluto's `Lock` parser starts accepting an absent
/// `partial_deposit_data` key, at which point this case should move back
/// into the strict `lock_hashes_and_verification` loop.
#[test]
fn lock_known_divergence_missing_partial_deposit_data() {
    let suite = load_suite("cluster_hashing");
    let case = suite["lock"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == LOCK_KNOWN_DIVERGENCE)
        .expect("validator_without_deposit_data present");

    let err = serde_json::from_value::<Lock>(case["input"].clone())
        .expect_err("expected pluto to still reject an absent partial_deposit_data key");
    assert!(
        err.to_string().contains("partial_deposit_data"),
        "unexpected error shape, pluto's rejection reason may have changed: {err}"
    );
}

/// `real_keys_3_of_4` is the only lock case with real signatures: its
/// `signature_aggregate` is a plain BLS aggregate of the lock hash over all
/// four private shares, and its `node_signatures` are secp256k1 signatures of
/// the lock hash by each operator's real ENR key. Its operator and creator
/// EIP-712 signatures are placeholder bytes (charon's signing helpers for
/// those are not exported for vector generation), so `Lock::verify_signatures`
/// — which checks the definition's EIP-712 signatures first and returns on
/// the first error — always rejects this case at that stage. `verify_hashes`
/// covers the hash chain (lock hash, and the definition hash it embeds); the
/// BLS aggregate and node-signature checks are private methods invoked only
/// after the EIP-712 stage, so they cannot be exercised standalone from this
/// external crate. See the Results row / Findings entry for `cluster_hashing`
/// for the reachability discussion.
#[tokio::test]
async fn real_keys_lock_verifies_end_to_end() {
    let suite = load_suite("cluster_hashing");
    let case = suite["lock"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "real_keys_3_of_4")
        .expect("real_keys_3_of_4 present");

    let lock: Lock = serde_json::from_value(case["input"].clone()).expect("parse real_keys_3_of_4");

    lock.verify_hashes().expect("hashes");

    // A no-op EL client: it skips only contract-based (EIP-1271) signature
    // verification, which this case does not use.
    let eth1 = pluto_eth1wrap::EthClient::new("")
        .await
        .expect("noop eth client");

    let err = lock
        .verify_signatures(&eth1)
        .await
        .expect_err("placeholder operator/creator EIP-712 signatures must not verify");
    assert!(
        matches!(
            err,
            pluto_cluster::lock::LockError::DefinitionSignaturesVerificationFailed(_)
        ),
        "expected rejection at the definition EIP-712 signature stage, got {err:?}"
    );
}
