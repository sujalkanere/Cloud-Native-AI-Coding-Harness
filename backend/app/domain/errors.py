"""
Domain Exception Hierarchy for Cloud-Native AI Coding Harness.

Typed domain errors adhering strictly to PROJECT.md:
- Pure Python exceptions, zero framework dependencies.
- Map cleanly to HTTP status codes at the API layer (404, 409, 400).
"""


class DomainError(Exception):
    """Base exception for all domain errors."""


class PathTraversalError(DomainError):
    """Raised when file access attempts to escape the /workspace boundary."""


class TarbombError(DomainError):
    """Raised when an untrusted archive contains unsafe entries or exceeds limits."""


class SSRFSecurityError(DomainError):
    """Raised when a repository clone URL resolves to private, loopback, or link-local addresses."""


class FreshVerificationError(DomainError):
    """Raised when finish is called without fresh passing tests under verification=required."""


class HeadroomValidationError(DomainError):
    """Raised when total tmpfs mounts exceed 60% of container memory limit."""


class InvalidStateTransitionError(DomainError):
    """Raised when a requested run lifecycle transition is invalid (maps to HTTP 409)."""


class EntityNotFoundError(DomainError):
    """Raised when a run or resource is not found or owned by another user (maps to HTTP 404)."""


class AuthenticationError(DomainError):
    """Raised when authentication fails (maps to HTTP 401)."""

