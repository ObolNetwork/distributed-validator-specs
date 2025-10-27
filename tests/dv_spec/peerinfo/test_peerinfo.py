"""Tests for the PeerInfo protocol specification."""

from datetime import datetime, timedelta

import pytest

from dv_spec.subspecs.peerinfo import (
    PROTOCOL_ID,
    PeerInfo,
    calculate_clock_offset,
    is_compatible_version,
    validate_git_hash,
)
from dv_spec.subspecs.peerinfo.helpers import (
    clamp_clock_offset,
    parse_semantic_version,
)


class TestProtocolID:
    """Tests for protocol identifier."""

    def test_protocol_id_format(self) -> None:
        """Test protocol ID has correct format."""
        assert PROTOCOL_ID == "/charon/peerinfo/2.0.0"
        assert PROTOCOL_ID.startswith("/charon/")
        assert PROTOCOL_ID.endswith("/2.0.0")


class TestPeerInfoMessage:
    """Tests for PeerInfo message model."""

    def test_create_valid_peerinfo(self) -> None:
        """Test creating a valid PeerInfo message."""
        peer_info = PeerInfo(
            charon_version="v1.2.3",
            lock_hash=b"\xab\xcd\xef" * 10 + b"\x12\x34",
            git_hash="abc1234",
            sent_at=datetime(2025, 1, 27, 12, 0, 0),
            started_at=datetime(2025, 1, 27, 10, 0, 0),
            builder_api_enabled=True,
            nickname="node-alpha",
        )

        assert peer_info.charon_version == "v1.2.3"
        assert len(peer_info.lock_hash) == 32
        assert peer_info.git_hash == "abc1234"
        assert peer_info.sent_at == datetime(2025, 1, 27, 12, 0, 0)
        assert peer_info.started_at == datetime(2025, 1, 27, 10, 0, 0)
        assert peer_info.builder_api_enabled is True
        assert peer_info.nickname == "node-alpha"

    def test_peerinfo_without_nickname(self) -> None:
        """Test PeerInfo message without optional nickname."""
        peer_info = PeerInfo(
            charon_version="v1.2.3",
            lock_hash=b"\x00" * 32,
            git_hash="abc1234",
            sent_at=datetime.now(),
            started_at=datetime.now(),
            builder_api_enabled=False,
        )

        assert peer_info.nickname is None

    def test_invalid_git_hash_length(self) -> None:
        """Test validation rejects invalid git hash length."""
        with pytest.raises(ValueError, match="must be exactly 7 characters"):
            PeerInfo(
                charon_version="v1.2.3",
                lock_hash=b"\x00" * 32,
                git_hash="abc12",  # Too short
                sent_at=datetime.now(),
                started_at=datetime.now(),
                builder_api_enabled=True,
            )

    def test_invalid_git_hash_chars(self) -> None:
        """Test validation rejects non-hex characters."""
        with pytest.raises(ValueError, match="must be hexadecimal"):
            PeerInfo(
                charon_version="v1.2.3",
                lock_hash=b"\x00" * 32,
                git_hash="xyz1234",  # Invalid hex
                sent_at=datetime.now(),
                started_at=datetime.now(),
                builder_api_enabled=True,
            )

    def test_git_hash_normalized_to_lowercase(self) -> None:
        """Test git hash is normalized to lowercase."""
        peer_info = PeerInfo(
            charon_version="v1.2.3",
            lock_hash=b"\x00" * 32,
            git_hash="ABC1234",  # Uppercase
            sent_at=datetime.now(),
            started_at=datetime.now(),
            builder_api_enabled=True,
        )

        assert peer_info.git_hash == "abc1234"

    def test_nickname_max_length(self) -> None:
        """Test nickname length validation."""
        # Valid nickname at max length
        peer_info = PeerInfo(
            charon_version="v1.2.3",
            lock_hash=b"\x00" * 32,
            git_hash="abc1234",
            sent_at=datetime.now(),
            started_at=datetime.now(),
            builder_api_enabled=True,
            nickname="a" * 32,
        )
        assert peer_info.nickname is not None
        assert len(peer_info.nickname) == 32

        # Invalid nickname exceeds max length
        with pytest.raises(ValueError, match="cannot exceed 32 characters"):
            PeerInfo(
                charon_version="v1.2.3",
                lock_hash=b"\x00" * 32,
                git_hash="abc1234",
                sent_at=datetime.now(),
                started_at=datetime.now(),
                builder_api_enabled=True,
                nickname="a" * 33,
            )


class TestGitHashValidation:
    """Tests for git hash validation helper."""

    def test_valid_git_hash(self) -> None:
        """Test validation of valid git hashes."""
        assert validate_git_hash("abc1234") is True
        assert validate_git_hash("0000000") is True
        assert validate_git_hash("fffffff") is True
        assert validate_git_hash("1a2b3c4") is True

    def test_valid_git_hash_uppercase(self) -> None:
        """Test validation accepts uppercase (case-insensitive)."""
        assert validate_git_hash("ABC1234") is True
        assert validate_git_hash("FFFFFFF") is True

    def test_invalid_git_hash_length(self) -> None:
        """Test validation rejects wrong length."""
        assert validate_git_hash("abc12") is False  # Too short
        assert validate_git_hash("abc12345") is False  # Too long

    def test_invalid_git_hash_chars(self) -> None:
        """Test validation rejects invalid characters."""
        assert validate_git_hash("xyz1234") is False
        assert validate_git_hash("abc123g") is False
        assert validate_git_hash("abc-234") is False


class TestSemanticVersionParsing:
    """Tests for semantic version parsing."""

    def test_parse_simple_version(self) -> None:
        """Test parsing simple version."""
        major, minor, patch, prerelease = parse_semantic_version("v1.2.3")
        assert major == 1
        assert minor == 2
        assert patch == 3
        assert prerelease == ""

    def test_parse_version_with_prerelease(self) -> None:
        """Test parsing version with prerelease."""
        major, minor, patch, prerelease = parse_semantic_version("v1.2.3-rc1")
        assert major == 1
        assert minor == 2
        assert patch == 3
        assert prerelease == "rc1"

    def test_parse_version_without_v_prefix(self) -> None:
        """Test parsing version without 'v' prefix."""
        major, minor, patch, prerelease = parse_semantic_version("1.2.3")
        assert major == 1
        assert minor == 2
        assert patch == 3

    def test_parse_version_without_patch(self) -> None:
        """Test parsing version without patch number."""
        major, minor, patch, prerelease = parse_semantic_version("v1.2")
        assert major == 1
        assert minor == 2
        assert patch == 0

    def test_parse_invalid_version(self) -> None:
        """Test parsing invalid version formats."""
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_semantic_version("v1")

        with pytest.raises(ValueError, match="Invalid version format"):
            parse_semantic_version("invalid")


class TestVersionCompatibility:
    """Tests for version compatibility checking."""

    def test_same_version_compatible(self) -> None:
        """Test same version is compatible."""
        assert is_compatible_version("v1.2.3", ["v1.2.3"]) is True

    def test_newer_patch_compatible(self) -> None:
        """Test newer patch version is compatible."""
        assert is_compatible_version("v1.2.4", ["v1.2.3"]) is True
        assert is_compatible_version("v1.2.10", ["v1.2.3"]) is True

    def test_newer_minor_compatible(self) -> None:
        """Test newer minor version is compatible."""
        assert is_compatible_version("v1.3.0", ["v1.2.3"]) is True
        assert is_compatible_version("v1.10.0", ["v1.2.3"]) is True

    def test_newer_major_compatible(self) -> None:
        """Test newer major version is compatible."""
        assert is_compatible_version("v2.0.0", ["v1.2.3"]) is True

    def test_older_patch_compatible(self) -> None:
        """Test older patch with same minor is compatible."""
        assert is_compatible_version("v1.2.2", ["v1.2.3"]) is True
        assert is_compatible_version("v1.2.0", ["v1.2.3"]) is True

    def test_older_minor_incompatible(self) -> None:
        """Test older minor version is incompatible."""
        assert is_compatible_version("v1.1.9", ["v1.2.3"]) is False
        assert is_compatible_version("v1.0.0", ["v1.2.3"]) is False

    def test_different_minor_incompatible(self) -> None:
        """Test different minor version is incompatible."""
        assert is_compatible_version("v1.1.0", ["v1.2.3"]) is False

    def test_multiple_supported_versions(self) -> None:
        """Test compatibility with multiple supported versions."""
        supported = ["v1.2.3", "v1.1.5"]

        # Compatible with first (1.2.x)
        assert is_compatible_version("v1.2.4", supported) is True
        assert is_compatible_version("v1.2.0", supported) is True

        # Compatible with second (1.1.x)
        assert is_compatible_version("v1.1.6", supported) is True
        assert is_compatible_version("v1.1.0", supported) is True

        # Incompatible with neither
        assert is_compatible_version("v1.0.0", supported) is False

    def test_prerelease_compatible(self) -> None:
        """Test prerelease versions are compatible."""
        assert is_compatible_version("v1.2.3-rc1", ["v1.2.3"]) is True
        assert is_compatible_version("v1.2.3", ["v1.2.3-rc1"]) is True

    def test_invalid_version_incompatible(self) -> None:
        """Test invalid version format is incompatible."""
        assert is_compatible_version("invalid", ["v1.2.3"]) is False
        assert is_compatible_version("v1.2.3", ["invalid"]) is False


class TestClockOffset:
    """Tests for clock offset calculation."""

    def test_no_offset(self) -> None:
        """Test calculation with no clock offset."""
        sent = datetime(2025, 1, 27, 12, 0, 1)
        received = datetime(2025, 1, 27, 12, 0, 1)
        rtt = timedelta(seconds=0)

        offset = calculate_clock_offset(sent, received, rtt)
        assert offset.total_seconds() == 0

    def test_positive_offset(self) -> None:
        """Test calculation with peer clock ahead."""
        sent = datetime(2025, 1, 27, 12, 0, 2)
        received = datetime(2025, 1, 27, 12, 0, 1)
        rtt = timedelta(seconds=0)

        offset = calculate_clock_offset(sent, received, rtt)
        assert offset.total_seconds() == 1.0  # Peer is 1 second ahead

    def test_negative_offset(self) -> None:
        """Test calculation with peer clock behind."""
        sent = datetime(2025, 1, 27, 12, 0, 0)
        received = datetime(2025, 1, 27, 12, 0, 1)
        rtt = timedelta(seconds=0)

        offset = calculate_clock_offset(sent, received, rtt)
        assert offset.total_seconds() == -1.0  # Peer is 1 second behind

    def test_offset_with_rtt(self) -> None:
        """Test calculation accounting for RTT."""
        # Peer sent at 12:00:30
        # We received at 12:00:30 (local time)
        # RTT is 2 seconds
        # Expected: peer sent at 12:00:29 (our time)
        # Actual: peer sent at 12:00:30 (their time)
        # Offset: +1 second (peer ahead)

        sent = datetime(2025, 1, 27, 12, 0, 30)
        received = datetime(2025, 1, 27, 12, 0, 30)
        rtt = timedelta(seconds=2)

        offset = calculate_clock_offset(sent, received, rtt)
        assert offset.total_seconds() == 1.0

    def test_clamp_offset_within_bounds(self) -> None:
        """Test clamping doesn't affect values within bounds."""
        offset = timedelta(minutes=30)
        clamped = clamp_clock_offset(offset)
        assert clamped == offset

    def test_clamp_offset_positive_overflow(self) -> None:
        """Test clamping positive overflow."""
        offset = timedelta(hours=2)
        clamped = clamp_clock_offset(offset, max_hours=1)
        assert clamped == timedelta(hours=1)

    def test_clamp_offset_negative_overflow(self) -> None:
        """Test clamping negative overflow."""
        offset = timedelta(hours=-2)
        clamped = clamp_clock_offset(offset, max_hours=1)
        assert clamped == timedelta(hours=-1)


class TestPeerInfoIntegration:
    """Integration tests for the PeerInfo protocol."""

    def test_full_exchange_simulation(self) -> None:
        """Test simulating a full peer info exchange."""
        # Node A creates request
        request_time = datetime(2025, 1, 27, 12, 0, 0)
        request = PeerInfo(
            charon_version="v1.2.3",
            lock_hash=b"\xaa" * 32,
            git_hash="abc1234",
            sent_at=request_time,
            started_at=datetime(2025, 1, 27, 10, 0, 0),
            builder_api_enabled=True,
            nickname="node-a",
        )

        # Node B receives and responds (clock is 1 second ahead)
        response_time = datetime(2025, 1, 27, 12, 0, 2)  # 2 seconds later
        response = PeerInfo(
            charon_version="v1.2.4",  # Newer patch version
            lock_hash=b"\xaa" * 32,  # Same lock hash
            git_hash="def5678",
            sent_at=response_time,
            started_at=datetime(2025, 1, 27, 9, 0, 0),
            builder_api_enabled=True,
            nickname="node-b",
        )

        # Node A receives response
        receive_time = datetime(2025, 1, 27, 12, 0, 2)
        rtt = receive_time - request_time  # 2 seconds

        # Calculate clock offset
        offset = calculate_clock_offset(response.sent_at, receive_time, rtt)

        # Expected: response sent at 12:00:02 (their time)
        # We received at 12:00:02 (our time)
        # RTT is 2 seconds, so half-trip is 1 second
        # Expected sent time: 12:00:01 (our time)
        # Actual sent time: 12:00:02 (their time)
        # Offset: +1 second (peer ahead)
        assert offset.total_seconds() == 1.0

        # Check version compatibility
        assert is_compatible_version(response.charon_version, [request.charon_version])

        # Check lock hash match
        assert response.lock_hash == request.lock_hash

        # Validate git hash
        assert validate_git_hash(response.git_hash)

    def test_incompatible_peer_detection(self) -> None:
        """Test detecting incompatible peers."""
        my_version = "v1.2.3"

        # Create response from incompatible peer
        incompatible_peer = PeerInfo(
            charon_version="v1.1.0",  # Older minor version
            lock_hash=b"\xbb" * 32,  # Different lock hash
            git_hash="abc1234",
            sent_at=datetime.now(),
            started_at=datetime.now(),
            builder_api_enabled=False,  # Different builder API setting
            nickname="old-node",
        )

        # Check version incompatibility
        assert not is_compatible_version(incompatible_peer.charon_version, [my_version])

        # Lock hash mismatch would be detected by comparison
        my_lock_hash = b"\xaa" * 32
        assert incompatible_peer.lock_hash != my_lock_hash

        # Builder API mismatch would be detected
        my_builder_api = True
        assert incompatible_peer.builder_api_enabled != my_builder_api
