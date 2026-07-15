"""Tests for DKG sync protocol messages."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from dv_spec.subspecs.dkg_sync.message import DKG_SYNC_PROTOCOL_ID, MsgSync


def _make_msg_sync(**overrides: object) -> MsgSync:
    """Build a valid MsgSync, with optional field overrides."""
    fields: dict[str, object] = {
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "hash_signature": b"\x01" * 65,
        "version": "1.0.0",
        "step": 0,
    }
    fields.update(overrides)
    return MsgSync(**fields)


class TestMsgSync:
    """Test MsgSync message validation."""

    def test_protocol_id(self) -> None:
        """Test the sync protocol ID (note the trailing slash)."""
        assert DKG_SYNC_PROTOCOL_ID == "/charon/dkg/sync/1.0.0/"

    def test_nickname_defaults_empty(self) -> None:
        """Test nickname defaults to empty string when not configured."""
        assert _make_msg_sync().nickname == ""

    def test_nickname_accepted(self) -> None:
        """Test a nickname up to 32 characters is accepted."""
        assert _make_msg_sync(nickname="a" * 32).nickname == "a" * 32

    def test_nickname_too_long_rejected(self) -> None:
        """Test a nickname over 32 characters is rejected."""
        with pytest.raises(ValidationError):
            _make_msg_sync(nickname="a" * 33)
