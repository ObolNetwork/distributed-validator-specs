"""PeerInfo protocol message definitions."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PeerInfo(BaseModel):
    """
    PeerInfo message exchanged between Charon nodes.

    Contains metadata about a peer including version, configuration,
    timing information, and operational settings.
    """

    charon_version: str = Field(
        description="Semantic version of Charon (e.g., 'v1.2.3', 'v1.2.3-rc1')"
    )
    lock_hash: bytes = Field(description="SHA-256 hash of the cluster lock file")
    git_hash: str = Field(description="7-character Git commit SHA")
    sent_at: datetime = Field(description="Timestamp when the message was sent")
    started_at: datetime = Field(description="Timestamp when the node started")
    builder_api_enabled: bool = Field(description="Whether MEV-Boost builder API is enabled")
    nickname: Optional[str] = Field(
        default=None, description="Human-friendly peer identifier (max 32 chars)"
    )

    @field_validator("git_hash")
    @classmethod
    def validate_git_hash(cls, v: str) -> str:
        """Validate git hash matches expected format."""
        if len(v) != 7:
            raise ValueError("git_hash must be exactly 7 characters")
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError("git_hash must be hexadecimal")
        return v.lower()

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v: Optional[str]) -> Optional[str]:
        """Validate nickname length."""
        if v is not None and len(v) > 32:
            raise ValueError("nickname cannot exceed 32 characters")
        return v
