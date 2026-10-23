"""Tests for deposit amounts, withdrawal credentials and signing roots.

The roots are checked against values Charon and Teku produced, so these tests
are cross-implementation checks rather than restatements of the code.
"""

from __future__ import annotations

import pytest

from dv_spec.cluster.deposit import (
    GWEI_PER_ETH,
    check_deposit_amount,
    default_deposit_amounts,
    deposit_message_root,
    deposit_signing_root,
    withdrawal_credentials,
)
from dv_spec.cluster.lock import Registration
from dv_spec.cluster.signing import DOMAIN_DEPOSIT, compute_domain
from dv_spec.cluster.verification import registration_signing_root
from dv_spec.crypto import bls

ADDRESS = "0x321dcb529f3945bc94fecea9d3bc5caf35253b94"


def test_mainnet_deposit_domain() -> None:
    # The well-known mainnet DOMAIN_DEPOSIT, as deposit tooling hard-codes it.
    assert compute_domain(DOMAIN_DEPOSIT, bytes(4)).hex() == (
        "03000000f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a9"
    )


def test_withdrawal_credentials_layout() -> None:
    raw = bytes.fromhex(ADDRESS[2:])

    assert withdrawal_credentials(ADDRESS, compounding=False) == b"\x01" + bytes(11) + raw
    assert withdrawal_credentials(ADDRESS, compounding=True) == b"\x02" + bytes(11) + raw


def test_withdrawal_credentials_need_a_valid_address() -> None:
    with pytest.raises(ValueError, match="invalid address"):
        withdrawal_credentials(ADDRESS[:-2], compounding=False)


def test_charon_deposit_data_verifies() -> None:
    # The second entry of charon's eth2util/deposit/testdata/
    # TestMarshalDepositData.golden: goerli fork version, 0x02 credentials.
    pubkey = bytes.fromhex(
        "813f5d2697f76841a752ef8c1ac11d1bb76e07003799c5745f8a569214653810"
        "def3b60920b54fb0ab3cb6deb08c3972"
    )
    credentials = withdrawal_credentials(ADDRESS, compounding=True)
    signature = bytes.fromhex(
        "b9bc77c52be591255d52ef25b7f2e0feb668329983619b0e23b5caf2d5768b3a"
        "9661079eaf68564eb5d743b531252aad058a9d0b48a87af601765176699248568d"
        "8bd7dd0539e38658c572ad628e1f0854a797378bf2125a08d1beb685faef91"
    )
    amount = 32 * GWEI_PER_ETH

    assert deposit_message_root(pubkey, credentials, amount).hex() == (
        "6dcf9ebf537997129102c7d74f3e54bd5446d608eb2d4fb15a53e3362e775a9b"
    )

    goerli = bytes.fromhex("00001020")
    assert bls.verify(pubkey, deposit_signing_root(pubkey, credentials, amount, goerli), signature)
    # The same signature is not valid on another network.
    assert not bls.verify(
        pubkey, deposit_signing_root(pubkey, credentials, amount, bytes(4)), signature
    )


def test_teku_builder_registration_verifies() -> None:
    # Charon's eth2util/registration TestVerifySignedRegistration, whose data
    # came from Teku: signed on Hoodi with the key below.
    secret = bytes.fromhex("345768c0245f1dc702df9e50e811002f61ebb2680b3d5931527ef59f96cbaf9b")
    message = Registration(
        fee_recipient=bytes.fromhex("000000000000000000000000000000000000dead"),
        gas_limit=30000000,
        timestamp=1646092800,
        pubkey=bytes.fromhex(
            "86966350b672bd502bfbdb37a6ea8a7392e8fb7f5ebb5c5e2055f4ee168ebfab"
            "0fef63084f28c9f62c3ba71f825e527e"
        ),
    )
    signature = bytes.fromhex(
        "838c82166e22fc27998fee74319daf42545f9fd32ae0e5d69319c888739a2c81"
        "7f82aab48f04f165e32304d2ab8d317c1318d6d907dbe6372417fcfc4e3f0b55"
        "0c357d5087abda4b80c021a64d2463e43efb017eeb1cef0dd92e38770b9628a1"
    )
    root = registration_signing_root(message, bytes.fromhex("10000910"))

    assert bls.verify(bls.secret_to_pubkey(secret), root, signature)


@pytest.mark.parametrize(
    ("amount", "compounding", "valid"),
    [
        (GWEI_PER_ETH, False, True),
        (GWEI_PER_ETH - 1, False, False),
        (32 * GWEI_PER_ETH, False, True),
        (32 * GWEI_PER_ETH + 1, False, False),
        (2048 * GWEI_PER_ETH, True, True),
        (2048 * GWEI_PER_ETH + 1, True, False),
    ],
)
def test_deposit_amount_bounds(amount: int, compounding: bool, valid: bool) -> None:
    if valid:
        check_deposit_amount(amount, compounding)
        return

    with pytest.raises(ValueError, match="deposit amount out of range"):
        check_deposit_amount(amount, compounding)


def test_default_deposit_amounts_match_charon() -> None:
    # deposit.DefaultDepositAmounts, which charon's DKG uses when a v1.8+
    # definition lists no amounts.
    assert default_deposit_amounts(False) == (GWEI_PER_ETH, 32 * GWEI_PER_ETH)
    assert default_deposit_amounts(True) == (
        GWEI_PER_ETH,
        8 * GWEI_PER_ETH,
        32 * GWEI_PER_ETH,
        256 * GWEI_PER_ETH,
    )
