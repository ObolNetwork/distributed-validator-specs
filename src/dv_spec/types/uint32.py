"""Unsigned 32-bit Integer Type Specification."""

from pydantic import Field
from typing_extensions import Annotated

UINT32_MAX = 2**32 - 1
"""The maximum value of an unsigned 32-bit integer (2**32 - 1)."""

Uint32 = Annotated[int, Field(ge=0, le=UINT32_MAX)]
"""A type alias to represent a uint32."""
