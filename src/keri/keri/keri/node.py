"""
KERI Node
==========
Top-level KERINode class that wires all subsystems together into a single
coherent runtime matching the architecture diagram.

Usage::

    from keri import KERINode
    from keri.identity import RoleConfig

    node = KERINode.create(
        RoleConfig(org="myorg", block="main", instance="node-1")
    )
    aid = node.create_identity()
    node.ingest({"sender": aid, "payload": {"action": "hello"}})
    node.process()
    outputs = node.collect_outputs()
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .core.models import GenesisPolicy, Message, KeyPair
from .core.crypto import generate_key_pair
from .core.exceptions import KERIError

# Identity
from .identity.governance import RoleConfig, GenesisPolicyLoader, GovernanceRulesLoader
from .identity.kel import (
    KELStore, KELSelfValidator, IdentityStateDB,
    KELManager, InceptionEngine, IdentityAPI,
)

# Key Management
from .key_management.kms import (
    ExternalWalletStorage, HotKeysCache, PreRotatedKeysSaver,
    RecoveryKeysManager, KeyVault,
)

# Input
from .input.gateway import (
    InputParser, InputQueue, SenderCredentialVerifier, InputGatewayModule,
)

# Credentials
from .credentials.authority import (
    ACDCSchemaManager, CredentialStoreCache, RevocationCacheAPI,
    DelegationChainResolver, CredentialIssuer, CredentialVerifier,
)

# Trust
from .trust.engine import (
    DecisionContextBuilder, PolicyEngine, TrustGuard,
)

# Evidence
from .evidence.audit import (
    EvidenceBuilder, EvidenceHasher, EvidenceHashSigner,
    EvidenceStoreAPI, EvidencePipeline,
)

# Output
from .output.manager import (
    OutputQueue, OutputSigner, OutputManager, OutputCollector, OutputEnvelope,
)


class KERINode:
    """
    Full KERI node: all subsystems wired together.
    """

    def __init__(
        self,
        # Identity layer
        inception_engine: InceptionEngine,
        identity_api: IdentityAPI,
        # Key Management
        key_vault: KeyVault,
        # Input
        input_gateway: InputGatewayModule,
        # Credentials
        credential_issuer: CredentialIssuer,
        credential_verifier: CredentialVerifier,
        revocation_cache: RevocationCacheAPI,
        schema_manager: ACDCSchemaManager,
        # Trust
        trust_guard: TrustGuard,
        # Evidence
        evidence_pipeline: EvidencePipeline,
        evidence_store: EvidenceStoreAPI,
        # Output
        output_manager: OutputManager,
        output_collector: OutputCollector,
        # Policy
        active_policy: Optional[GenesisPolicy] = None,
    ) -> None:
        self.inception_engine = inception_engine
        self.identity_api = identity_api
        self.key_vault = key_vault
        self.input_gateway = input_gateway
        self.credential_issuer = credential_issuer
        self.credential_verifier = credential_verifier
        self.revocation_cache = revocation_cache
        self.schema_manager = schema_manager
        self.trust_guard = trust_guard
        self.evidence_pipeline = evidence_pipeline
        self.evidence_store = evidence_store
        self.output_manager = output_manager
        self.output_collector = output_collector
        self.active_policy = active_policy

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        role_config: RoleConfig,
        use_external_wallet: bool = False,
        evidence_signing_key: str = "",
        output_signing_key: str = "",
    ) -> "KERINode":
        """
        Factory: instantiate and wire all subsystems from a RoleConfig.
        """
        # --- Governance ---
        policy_loader = GenesisPolicyLoader()
        rules_loader = GovernanceRulesLoader()
        policy = policy_loader.load(role_config)
        rules_loader.validate_policy(policy)

        # --- Identity ---
        kel_store = KELStore()
        kel_state_db = IdentityStateDB()
        kel_validator = KELSelfValidator(kel_store)
        kel_manager = KELManager(kel_store, kel_validator, kel_state_db)
        inception_engine = InceptionEngine(kel_manager)
        identity_api = IdentityAPI(kel_manager)

        # --- Key Management ---
        external_wallet = ExternalWalletStorage() if use_external_wallet else None
        hot_keys = HotKeysCache()
        pre_rotation = PreRotatedKeysSaver(wallet=external_wallet)
        recovery = RecoveryKeysManager(wallet=external_wallet)
        key_vault = KeyVault(
            hot_keys=hot_keys,
            pre_rotation=pre_rotation,
            recovery=recovery,
            external_wallet=external_wallet,
            use_external_storage=use_external_wallet,
        )

        # --- Credentials ---
        schema_manager = ACDCSchemaManager()
        cred_store = CredentialStoreCache()
        revocation_cache = RevocationCacheAPI()
        delegation_resolver = DelegationChainResolver(cred_store, identity_api)
        credential_issuer = CredentialIssuer(schema_manager, cred_store, identity_api)
        credential_verifier = CredentialVerifier(
            cred_store, revocation_cache, delegation_resolver, identity_api
        )

        # --- Input ---
        parser = InputParser()
        input_queue = InputQueue()
        sender_verifier = SenderCredentialVerifier(identity_api)
        input_gateway = InputGatewayModule(parser, input_queue, sender_verifier)

        # --- Trust ---
        ctx_builder = DecisionContextBuilder(identity_api, credential_verifier, cred_store)
        policy_engine = PolicyEngine()
        trust_guard = TrustGuard(ctx_builder, policy_engine, policy)

        # --- Evidence ---
        ev_builder = EvidenceBuilder()
        ev_hasher = EvidenceHasher()
        ev_signer = EvidenceHashSigner(evidence_signing_key)
        ev_store = EvidenceStoreAPI()
        evidence_pipeline = EvidencePipeline(ev_builder, ev_hasher, ev_signer, ev_store)

        # --- Output ---
        out_queue = OutputQueue()
        out_signer = OutputSigner(output_signing_key)
        output_manager = OutputManager(out_queue, out_signer)
        output_collector = OutputCollector(out_queue)

        return cls(
            inception_engine=inception_engine,
            identity_api=identity_api,
            key_vault=key_vault,
            input_gateway=input_gateway,
            credential_issuer=credential_issuer,
            credential_verifier=credential_verifier,
            revocation_cache=revocation_cache,
            schema_manager=schema_manager,
            trust_guard=trust_guard,
            evidence_pipeline=evidence_pipeline,
            evidence_store=ev_store,
            output_manager=output_manager,
            output_collector=output_collector,
            active_policy=policy,
        )

    # ------------------------------------------------------------------
    # High-level convenience API
    # ------------------------------------------------------------------

    def create_identity(
        self,
        seed: Optional[str] = None,
        delegator_aid: Optional[str] = None,
    ) -> str:
        """
        Generate key pairs, run inception, return the new AID string.
        """
        assert self.active_policy is not None, "No active policy set"

        hot_pub, hot_priv = generate_key_pair(seed)
        prerot_pub, prerot_priv = generate_key_pair()

        hot_kp = KeyPair(public_key=hot_pub, private_key=hot_priv)
        prerot_kp = KeyPair(public_key=prerot_pub, private_key=prerot_priv)

        event = self.inception_engine.create_inception(
            policy=self.active_policy,
            hot_key_pair=hot_kp,
            pre_rotation_key_pair=prerot_kp,
            delegator_aid=delegator_aid,
            private_key_for_signing=hot_priv,
        )

        aid = event.aid
        self.key_vault.hot_keys.put(aid, hot_kp)
        self.key_vault.pre_rotation.save(aid, prerot_kp)
        return aid

    def ingest(self, raw: Any) -> Message:
        """Parse and enqueue an incoming message."""
        return self.input_gateway.ingest(raw)

    def process(self, timeout: float = 1.0) -> Optional[OutputEnvelope]:
        """
        Process one message from the input queue:
          verify → trust-check → build evidence → produce output.
        Returns an OutputEnvelope or None if queue was empty.
        """
        result: Optional[OutputEnvelope] = None

        def _handle(message: Message, sender_ok: bool) -> OutputEnvelope:
            nonlocal result
            allowed = sender_ok and self.trust_guard.is_allowed(message)
            if allowed:
                self.evidence_pipeline.process(message)
            envelope = self.output_manager.submit(
                message,
                payload={"allowed": allowed, **message.payload},
            )
            result = envelope
            return envelope

        try:
            self.input_gateway.process_next(_handle, timeout=timeout)
        except Exception:
            pass
        return result

    def collect_outputs(self) -> List[OutputEnvelope]:
        """Drain and return all pending output envelopes."""
        return self.output_collector.collect_all()

    def register_output_handler(
        self, handler: Callable[[OutputEnvelope], None]
    ) -> None:
        """Register a callback for every outbound envelope."""
        self.output_collector.register_handler(handler)
