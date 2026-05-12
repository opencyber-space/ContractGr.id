"""
KERI library exceptions.
"""


class KERIError(Exception):
    """Base exception for all KERI errors."""


class ValidationError(KERIError):
    """Raised when an event or credential fails validation."""


class KeyError(KERIError):  # noqa: A001
    """Raised on key management failures."""


class CredentialError(KERIError):
    """Raised on credential issuance or verification failures."""


class TrustError(KERIError):
    """Raised when trust evaluation fails."""


class PolicyError(KERIError):
    """Raised when a genesis or governance policy check fails."""


class IdentityError(KERIError):
    """Raised on AID / KEL resolution failures."""


class EvidenceError(KERIError):
    """Raised on evidence storage or hashing failures."""


class ParseError(KERIError):
    """Raised when input parsing fails."""
