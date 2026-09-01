"""Typed errors raised by the minimal Agent kernel."""

from __future__ import annotations


class AgentError(Exception):
    """Base exception for deterministic Agent-runtime failures."""


class AgentInputError(AgentError):
    """Raised when required input is missing or blank."""
