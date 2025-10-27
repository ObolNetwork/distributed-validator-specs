"""Helper functions for the PeerInfo protocol."""

import re
from datetime import datetime, timedelta
from typing import Tuple

# Protocol identifier
PROTOCOL_ID = "/charon/peerinfo/2.0.0"

# Git hash validation regex
GIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7}$")


def validate_git_hash(git_hash: str) -> bool:
    """
    Validate that a git hash matches the expected format.

    Args:
        git_hash: Git commit hash to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_git_hash("abc1234")
        True
        >>> validate_git_hash("xyz1234")
        False
        >>> validate_git_hash("abc12")
        False
    """
    return bool(GIT_HASH_PATTERN.match(git_hash.lower()))


def parse_semantic_version(version: str) -> Tuple[int, int, int, str]:
    """
    Parse a semantic version string into components.

    Args:
        version: Version string (e.g., "v1.2.3", "v1.2.3-rc1")

    Returns:
        Tuple of (major, minor, patch, prerelease)

    Raises:
        ValueError: If version string is invalid

    Example:
        >>> parse_semantic_version("v1.2.3")
        (1, 2, 3, '')
        >>> parse_semantic_version("v1.2.3-rc1")
        (1, 2, 3, 'rc1')
    """
    # Remove 'v' prefix if present
    version = version.lstrip("v")

    # Split on '-' to separate version from prerelease
    parts = version.split("-", 1)
    version_part = parts[0]
    prerelease = parts[1] if len(parts) > 1 else ""

    # Parse version numbers
    try:
        version_numbers = version_part.split(".")
        if len(version_numbers) < 2:
            raise ValueError(f"Invalid version format: {version}")

        major = int(version_numbers[0])
        minor = int(version_numbers[1])
        patch = int(version_numbers[2]) if len(version_numbers) > 2 else 0

        return (major, minor, patch, prerelease)
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid version format: {version}") from e


def is_compatible_version(peer_version: str, supported_versions: list[str]) -> bool:
    """
    Check if a peer's version is compatible with supported versions.

    Compatibility rules:
    1. Accept peers with newer versions (assume forward compatibility)
    2. Accept peers with matching minor version
    3. Reject peers with different minor versions (unless newer overall)

    Args:
        peer_version: Version string from peer
        supported_versions: List of supported version strings (sorted, newest first)

    Returns:
        True if compatible, False otherwise

    Example:
        >>> is_compatible_version("v1.2.4", ["v1.2.3", "v1.1.0"])
        True
        >>> is_compatible_version("v1.3.0", ["v1.2.3"])
        True
        >>> is_compatible_version("v1.1.0", ["v1.2.3"])
        False
    """
    try:
        peer_major, peer_minor, _, _ = parse_semantic_version(peer_version)
        latest_major, latest_minor, _, _ = parse_semantic_version(supported_versions[0])

        # Accept newer versions
        if peer_major > latest_major:
            return True
        if peer_major == latest_major and peer_minor > latest_minor:
            return True

        # Check if peer minor version matches any supported version
        for supported_version in supported_versions:
            sup_major, sup_minor, _, _ = parse_semantic_version(supported_version)
            if peer_major == sup_major and peer_minor == sup_minor:
                return True

        return False
    except ValueError:
        # Invalid version format
        return False


def calculate_clock_offset(sent_at: datetime, received_at: datetime, rtt: timedelta) -> timedelta:
    """
    Calculate clock offset between local and remote peer.

    The offset is calculated as:
        expected_sent_at = received_at - (rtt / 2)
        offset = sent_at - expected_sent_at

    A positive offset means the peer's clock is ahead.
    A negative offset means the peer's clock is behind.

    Args:
        sent_at: Timestamp from peer's response
        received_at: Local timestamp when response was received
        rtt: Round-trip time for the request-response

    Returns:
        Clock offset as timedelta

    Example:
        >>> from datetime import timedelta
        >>> sent = datetime(2025, 1, 27, 12, 0, 30)
        >>> received = datetime(2025, 1, 27, 12, 0, 30)
        >>> rtt = timedelta(seconds=2)
        >>> offset = calculate_clock_offset(sent, received, rtt)
        >>> offset.total_seconds()
        1.0
    """
    expected_sent_at = received_at - (rtt / 2)
    offset = sent_at - expected_sent_at
    return offset


def clamp_clock_offset(offset: timedelta, max_hours: int = 1) -> timedelta:
    """
    Clamp clock offset to a maximum range for metrics.

    Args:
        offset: Clock offset to clamp
        max_hours: Maximum hours (default: 1)

    Returns:
        Clamped offset

    Example:
        >>> from datetime import timedelta
        >>> clamp_clock_offset(timedelta(hours=2))
        datetime.timedelta(seconds=3600)
        >>> clamp_clock_offset(timedelta(hours=-2))
        datetime.timedelta(days=-1, seconds=82800)
    """
    max_offset = timedelta(hours=max_hours)
    min_offset = -max_offset

    if offset > max_offset:
        return max_offset
    if offset < min_offset:
        return min_offset
    return offset
