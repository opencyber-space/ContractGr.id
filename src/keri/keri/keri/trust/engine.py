"""
Trust and Decision Engine
==========================
Implements:
  - DecisionContextBuilder : assembles context (identity state, credentials, policy)
  - PolicyEngine           : evaluates rules from genesis policy
  - TrustGuard             : final gate that allows/denies message processing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.models import Message, GenesisPolicy, IdentityState, Credential
from ..core.exceptions import TrustError, PolicyError
from ..identity.kel import IdentityAPI
from ..credentials.authority import CredentialVerifier, CredentialStoreCache


# ---------------------------------------------------------------------------
# Decision Context
# ---------------------------------------------------------------------------

@dataclass
class DecisionContext:
    """
    Assembled context passed to the PolicyEngine.
    """
    message: Message
    sender_state: Optional[IdentityState]
    verified_credentials: List[Credential] = field(default_factory=list)
    policy: Optional[GenesisPolicy] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision Context Builder
# ---------------------------------------------------------------------------

class DecisionContextBuilder:
    """
    Builds a DecisionContext for a given message by gathering:
      - sender identity state
      - verified credentials
      - active genesis policy
    Corresponds to 'Decision context builder' in the diagram.
    """

    def __init__(
        self,
        identity_api: IdentityAPI,
        credential_verifier: CredentialVerifier,
        credential_store: CredentialStoreCache,
    ) -> None:
        self._identity_api = identity_api
        self._cred_verifier = credential_verifier
        self._cred_store = credential_store

    def build(self, message: Message, policy: Optional[GenesisPolicy] = None) -> DecisionContext:
        sender_state = self._identity_api.resolve_aid(message.sender_aid)
        verified_creds = []
        for cred_id in message.credentials:
            cred = self._cred_verifier.get_verified_credential(cred_id)
            if cred:
                verified_creds.append(cred)
        return DecisionContext(
            message=message,
            sender_state=sender_state,
            verified_credentials=verified_creds,
            policy=policy,
        )


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

@dataclass
class EvaluatedRules:
    passed: bool
    failed_rules: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """
    Evaluates a DecisionContext against the genesis policy rules.
    Corresponds to 'Policy engine (check based on the genesis policy)' in diagram.
    """

    def evaluate(self, context: DecisionContext) -> EvaluatedRules:
        failed: List[str] = []
        details: Dict[str, Any] = {}

        # Rule 1: sender must have a known AID
        if context.sender_state is None:
            failed.append("unknown_sender_aid")
            details["sender_aid"] = context.message.sender_aid

        # Rule 2: if policy defines required credentials, check they are present
        if context.policy:
            required_schemas = [
                r.get("required_schema")
                for r in context.policy.rules
                if r.get("type") == "credential_required"
            ]
            presented_schemas = {c.schema_id for c in context.verified_credentials}
            for schema_id in required_schemas:
                if schema_id and schema_id not in presented_schemas:
                    failed.append(f"missing_required_credential:{schema_id}")

            # Rule 3: check signing threshold only if creds are explicitly required
            threshold = context.policy.thresholds.get("signing", 1)
            if threshold > 1 and len(context.verified_credentials) < threshold:
                failed.append("below_signing_threshold")
                details["required"] = threshold
                details["provided"] = len(context.verified_credentials)

        passed = len(failed) == 0
        return EvaluatedRules(passed=passed, failed_rules=failed, details=details)


# ---------------------------------------------------------------------------
# Trust Guard
# ---------------------------------------------------------------------------

class TrustGuard:
    """
    Final gating component.  If the PolicyEngine approves, builds evidence;
    otherwise rejects the message.
    Corresponds to 'Trust Guard' in the diagram.
    """

    def __init__(
        self,
        context_builder: DecisionContextBuilder,
        policy_engine: PolicyEngine,
        active_policy: Optional[GenesisPolicy] = None,
    ) -> None:
        self._builder = context_builder
        self._engine = policy_engine
        self._policy = active_policy

    def set_policy(self, policy: GenesisPolicy) -> None:
        self._policy = policy

    def evaluate_message(self, message: Message) -> EvaluatedRules:
        """
        Build context and evaluate. Returns the rules evaluation result.
        """
        context = self._builder.build(message, self._policy)
        return self._engine.evaluate(context)

    def is_allowed(self, message: Message) -> bool:
        result = self.evaluate_message(message)
        return result.passed

    def assert_allowed(self, message: Message) -> None:
        """Raises TrustError if message is not allowed."""
        result = self.evaluate_message(message)
        if not result.passed:
            raise TrustError(
                f"Message {message.message_id} rejected. "
                f"Failed rules: {result.failed_rules}"
            )
