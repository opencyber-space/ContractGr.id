"""
KERI - Key Event Receipt Infrastructure Python Library
=======================================================
A pure-Python implementation of the KERI architecture covering:

  - Identity & KEL System   (keri.identity)
  - Key Management System   (keri.key_management)
  - Input Gateway           (keri.input)
  - Credentials & Authority (keri.credentials)
  - Trust & Decision Engine (keri.trust)
  - Audit & Evidence        (keri.evidence)
  - Output Pipeline         (keri.output)
  - Governance & Roles      (keri.identity.governance)

Quick start::

    from keri import KERINode
    from keri.identity import RoleConfig

    node = KERINode.create(
        RoleConfig(org="acme", block="main", instance="node-0",
                   witness_aids=[], signing_threshold=1)
    )
    aid = node.create_identity()
    node.ingest({"sender": aid, "payload": {"hello": "world"}})
    node.process()
    for env in node.collect_outputs():
        print(env.to_dict())
"""

from .node import KERINode
from .core import (
    KeyPair, Prefix, KELEvent, Credential, Message, Evidence,
    GenesisPolicy, IdentityState, EventType, CredentialStatus,
    KERIError, ValidationError, CredentialError, TrustError,
    PolicyError, IdentityError, EvidenceError, ParseError,
)

__version__ = "0.1.0"
__all__ = [
    "KERINode",
    "KeyPair", "Prefix", "KELEvent", "Credential", "Message", "Evidence",
    "GenesisPolicy", "IdentityState", "EventType", "CredentialStatus",
    "KERIError", "ValidationError", "CredentialError", "TrustError",
    "PolicyError", "IdentityError", "EvidenceError", "ParseError",
]
