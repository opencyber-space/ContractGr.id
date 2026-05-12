"""
Credentials and Authority System
==================================
Implements:
  - ACDCSchemaManager         : ACDC schema and templates management
  - CredentialStoreCache      : persistent credential cache API
  - RevocationCacheAPI        : revocation cache API
  - DelegationChainResolver   : resolves chain for delegations
  - CredentialIssuer          : issues ACDC credentials from schema templates
  - CredentialVerifier        : verifies credentials (cache + chain + revocation)
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.models import Credential, CredentialStatus
from ..core.crypto import sign, hash_data
from ..core.exceptions import CredentialError
from ..identity.kel import IdentityAPI


# ---------------------------------------------------------------------------
# ACDC Schema and Templates Management
# ---------------------------------------------------------------------------

@dataclass
class ACDCSchema:
    schema_id: str
    name: str
    version: str
    fields: Dict[str, Any]  # field_name -> type/constraints
    issuer_role: Optional[str] = None

    def validate_claims(self, claims: Dict[str, Any]) -> None:
        for required_field in self.fields:
            if self.fields[required_field].get("required") and required_field not in claims:
                raise CredentialError(
                    f"Missing required field '{required_field}' for schema {self.schema_id}"
                )


class ACDCSchemaManager:
    """
    Manages ACDC schemas and credential templates.
    Corresponds to 'ACDC Schemas and Templates management' in the diagram.
    """

    def __init__(self) -> None:
        self._schemas: Dict[str, ACDCSchema] = {}

    def register_schema(self, schema: ACDCSchema) -> None:
        self._schemas[schema.schema_id] = schema

    def get_schema(self, schema_id: str) -> Optional[ACDCSchema]:
        return self._schemas.get(schema_id)

    def list_schemas(self) -> List[str]:
        return list(self._schemas.keys())


# ---------------------------------------------------------------------------
# Credential Store Cache API
# ---------------------------------------------------------------------------

class CredentialStoreCache:
    """
    Cache for issued credentials.
    Corresponds to 'Credential store cache API' / 'Credentials cache' in diagram.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Credential] = {}

    def put(self, credential: Credential) -> None:
        self._store[credential.credential_id] = credential

    def get(self, credential_id: str) -> Optional[Credential]:
        return self._store.get(credential_id)

    def list_for_subject(self, subject_aid: str) -> List[Credential]:
        return [c for c in self._store.values() if c.subject_aid == subject_aid]

    def list_for_issuer(self, issuer_aid: str) -> List[Credential]:
        return [c for c in self._store.values() if c.issuer_aid == issuer_aid]

    def remove(self, credential_id: str) -> None:
        self._store.pop(credential_id, None)


# ---------------------------------------------------------------------------
# Revocation Cache API
# ---------------------------------------------------------------------------

class RevocationCacheAPI:
    """
    Caches revoked credential IDs.
    Corresponds to 'Revocation cache API' / 'Revoked credentials cache' in diagram.
    """

    def __init__(self) -> None:
        self._revoked: Dict[str, float] = {}  # credential_id -> revoked_at timestamp

    def revoke(self, credential_id: str) -> None:
        self._revoked[credential_id] = time.time()

    def is_revoked(self, credential_id: str) -> bool:
        return credential_id in self._revoked

    def revoked_at(self, credential_id: str) -> Optional[float]:
        return self._revoked.get(credential_id)


# ---------------------------------------------------------------------------
# Delegation Chain Resolver
# ---------------------------------------------------------------------------

class DelegationChainResolver:
    """
    Resolves the chain of delegations for a credential or AID.
    Corresponds to 'Delegation chain resolver' in the diagram.
    """

    def __init__(
        self,
        credential_store: CredentialStoreCache,
        identity_api: IdentityAPI,
    ) -> None:
        self._store = credential_store
        self._identity_api = identity_api

    def resolve_chain(self, credential_id: str) -> List[Credential]:
        """
        Returns the full chain of credentials from root to the given credential.
        """
        chain: List[Credential] = []
        current_id = credential_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            cred = self._store.get(current_id)
            if not cred:
                break
            chain.append(cred)
            # follow parent chain
            if cred.chain:
                current_id = cred.chain[0]
            else:
                break
        return list(reversed(chain))

    def resolve_delegation_chain(self, aid: str) -> List[str]:
        """Returns AID delegation chain via KEL delegator links."""
        chain = [aid]
        current = aid
        seen = set()
        while current and current not in seen:
            seen.add(current)
            state = self._identity_api.resolve_aid(current)
            if state and state.delegator:
                chain.append(state.delegator)
                current = state.delegator
            else:
                break
        return list(reversed(chain))


# ---------------------------------------------------------------------------
# Credential Issuer
# ---------------------------------------------------------------------------

class CredentialIssuer:
    """
    Issues ACDC credentials from schema templates.
    Credentials are derived from ACDC schema templates.
    Corresponds to 'Credential Issuer' in the diagram.
    """

    def __init__(
        self,
        schema_manager: ACDCSchemaManager,
        credential_store: CredentialStoreCache,
        identity_api: IdentityAPI,
    ) -> None:
        self._schemas = schema_manager
        self._store = credential_store
        self._identity_api = identity_api

    def issue(
        self,
        issuer_aid: str,
        subject_aid: str,
        schema_id: str,
        claims: Dict[str, Any],
        private_key: str = "",
        parent_credential_id: Optional[str] = None,
        expiry_seconds: Optional[float] = None,
    ) -> Credential:
        schema = self._schemas.get_schema(schema_id)
        if schema is None:
            raise CredentialError(f"Unknown schema: {schema_id}")
        schema.validate_claims(claims)

        # Verify issuer has an active AID
        if not self._identity_api.resolve_aid(issuer_aid):
            raise CredentialError(f"Issuer AID {issuer_aid} not found in identity system")

        expiry = time.time() + expiry_seconds if expiry_seconds else None
        cred = Credential(
            credential_id=str(uuid.uuid4()),
            issuer_aid=issuer_aid,
            subject_aid=subject_aid,
            schema_id=schema_id,
            claims=claims,
            status=CredentialStatus.ISSUED,
            expiry=expiry,
            chain=[parent_credential_id] if parent_credential_id else [],
        )

        if private_key:
            cred.signature = sign(cred.serialize(), private_key)

        self._store.put(cred)
        return cred


# ---------------------------------------------------------------------------
# Credential Verifier
# ---------------------------------------------------------------------------

class CredentialVerifier:
    """
    Verifies ACDC credentials via:
      1. Cache lookup
      2. Delegation chain resolution
      3. Revocation check
    Corresponds to 'Credential verifier' in the diagram.
    """

    def __init__(
        self,
        credential_store: CredentialStoreCache,
        revocation_cache: RevocationCacheAPI,
        delegation_resolver: DelegationChainResolver,
        identity_api: IdentityAPI,
    ) -> None:
        self._store = credential_store
        self._revocation = revocation_cache
        self._delegation = delegation_resolver
        self._identity_api = identity_api

    def verify(self, credential_id: str) -> bool:
        """Returns True if the credential is valid (cached, not revoked, chain valid)."""
        # Step 1: retrieve from cache
        cred = self._store.get(credential_id)
        if cred is None:
            return False

        # Step 2: check revocation cache
        if self._revocation.is_revoked(credential_id):
            return False

        # Step 3: check expiry
        if cred.expiry and time.time() > cred.expiry:
            return False

        # Step 4: verify issuer AID exists
        issuer_state = self._identity_api.resolve_aid(cred.issuer_aid)
        if issuer_state is None:
            return False

        # Step 5: check chain (all parent creds must also be valid)
        for parent_id in cred.chain:
            if not self.verify(parent_id):
                return False

        return True

    def get_verified_credential(self, credential_id: str) -> Optional[Credential]:
        if self.verify(credential_id):
            return self._store.get(credential_id)
        return None
