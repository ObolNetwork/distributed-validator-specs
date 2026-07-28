"""Unsigned 64-bit Integer Type Specification."""

from pydantic import Field
from typing_extensions import Annotated

UINT64_MAX = 2**64 - 1
"""The maximum value of an unsigned 64-bit integer (2**64 - 1)."""

Uint64 = Annotated[int, Field(ge=0, le=UINT64_MAX)]
"""A type alias to represent a uint64."""
