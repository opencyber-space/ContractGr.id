"""
Tests for the KERI library — covers all major subsystems.
Run with: python -m pytest tests/ -v
"""
import json
import time
import pytest

from keri import KERINode
from keri.core import (
    KELEvent, EventType, Message, Evidence,
    ValidationError, CredentialError, TrustError,
)
from keri.core.crypto import generate_key_pair, derive_next_key_digest, sign, prefix_from_public_key
from keri.identity import (
    RoleConfig, GenesisPolicyLoader, GovernanceRulesLoader,
    KELStore, KELSelfValidator, IdentityStateDB, KELManager,
    InceptionEngine, IdentityAPI,
)
from keri.key_management import (
    HotKeysCache, PreRotatedKeysSaver, RecoveryKeysManager, KeyVault, ExternalWalletStorage,
)
from keri.credentials import (
    ACDCSchema, ACDCSchemaManager, CredentialStoreCache, RevocationCacheAPI,
    DelegationChainResolver, CredentialIssuer, CredentialVerifier,
)
from keri.trust import DecisionContextBuilder, PolicyEngine, TrustGuard
from keri.evidence import EvidenceBuilder, EvidenceHasher, EvidenceHashSigner, EvidenceStoreAPI, EvidencePipeline
from keri.output import OutputQueue, OutputSigner, OutputManager, OutputCollector
from keri.core.models import KeyPair


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def role_config():
    return RoleConfig(
        org="testorg", block="main", instance="node-0",
        witness_aids=[], signing_threshold=1, rotation_threshold=1,
    )


@pytest.fixture
def policy(role_config):
    loader = GenesisPolicyLoader()
    return loader.load(role_config)


@pytest.fixture
def kel_components():
    store = KELStore()
    state_db = IdentityStateDB()
    validator = KELSelfValidator(store)
    manager = KELManager(store, validator, state_db)
    identity_api = IdentityAPI(manager)
    return store, state_db, validator, manager, identity_api


@pytest.fixture
def node(role_config):
    return KERINode.create(role_config)


# ============================================================================
# Crypto tests
# ============================================================================

class TestCrypto:
    def test_generate_key_pair(self):
        pub, priv = generate_key_pair()
        assert len(pub) == 64  # hex SHA-256
        assert len(priv) == 64

    def test_deterministic_key_pair(self):
        pub1, priv1 = generate_key_pair("seed123")
        pub2, priv2 = generate_key_pair("seed123")
        assert pub1 == pub2
        assert priv1 == priv2

    def test_prefix_from_public_key(self):
        pub, _ = generate_key_pair()
        prefix = prefix_from_public_key(pub)
        assert prefix.startswith("E")
        assert len(prefix) == 44

    def test_sign_and_verify(self):
        pub, priv = generate_key_pair()
        data = "hello world"
        sig = sign(data, priv)
        assert sig  # non-empty
        # same key produces same signature
        sig2 = sign(data, priv)
        assert sig == sig2

    def test_next_key_digest(self):
        pub, _ = generate_key_pair()
        digest = derive_next_key_digest(pub)
        assert len(digest) == 64


# ============================================================================
# Identity / KEL tests
# ============================================================================

class TestKELSystem:
    def test_inception_event(self, kel_components, policy):
        _, _, _, manager, identity_api = kel_components
        engine = InceptionEngine(manager)

        pub, priv = generate_key_pair()
        prerot_pub, _ = generate_key_pair()
        hot_kp = KeyPair(public_key=pub, private_key=priv)
        prerot_kp = KeyPair(public_key=prerot_pub, private_key="")

        event = engine.create_inception(policy, hot_kp, prerot_kp)
        assert event.seq_no == 0
        assert event.event_type == EventType.INCEPTION
        state = identity_api.resolve_aid(event.aid)
        assert state is not None
        assert state.seq_no == 0
        assert pub in state.current_keys

    def test_duplicate_inception_rejected(self, kel_components, policy):
        _, _, _, manager, _ = kel_components
        engine = InceptionEngine(manager)

        pub, priv = generate_key_pair()
        prerot_pub, _ = generate_key_pair()
        hot_kp = KeyPair(public_key=pub, private_key=priv)
        prerot_kp = KeyPair(public_key=prerot_pub, private_key="")

        engine.create_inception(policy, hot_kp, prerot_kp)
        # second inception for same AID must fail
        with pytest.raises(ValidationError):
            engine.create_inception(policy, hot_kp, prerot_kp)

    def test_seq_no_validation(self, kel_components, policy):
        store, _, validator, manager, identity_api = kel_components
        engine = InceptionEngine(manager)

        pub, priv = generate_key_pair()
        prerot_pub, _ = generate_key_pair()
        event = engine.create_inception(
            policy,
            KeyPair(pub, priv),
            KeyPair(prerot_pub, ""),
        )

        # interaction event with wrong seq_no
        bad_event = KELEvent(
            event_type=EventType.INTERACTION,
            aid=event.aid,
            seq_no=5,  # wrong — should be 1
            keys=[pub],
        )
        with pytest.raises(ValidationError):
            manager.process_event(bad_event)

    def test_governance_rules_loader(self, role_config, policy):
        loader = GovernanceRulesLoader()
        rules = loader.load_rules(policy)
        assert "thresholds" in rules
        assert rules["thresholds"]["signing"] == 1


# ============================================================================
# Key Management tests
# ============================================================================

class TestKeyManagement:
    def test_hot_keys_cache(self):
        cache = HotKeysCache()
        pub, priv = generate_key_pair()
        kp = KeyPair(pub, priv)
        cache.put("aid:1", kp)
        assert cache.get("aid:1") == kp
        cache.remove("aid:1")
        assert cache.get("aid:1") is None

    def test_pre_rotation_save_and_promote(self):
        cache = HotKeysCache()
        pre_rot = PreRotatedKeysSaver()
        pub, priv = generate_key_pair()
        kp = KeyPair(pub, priv)
        entry = pre_rot.save("aid:1", kp)
        assert entry.next_public_key == pub
        assert entry.next_key_digest

        promoted = pre_rot.promote_to_hot("aid:1")
        assert promoted is not None
        assert promoted.public_key == pub

    def test_key_vault_generate_and_sign(self):
        vault = KeyVault(HotKeysCache(), PreRotatedKeysSaver(), RecoveryKeysManager())
        kp = vault.generate_and_store_key_pair("aid:1")
        assert kp.public_key
        sig = vault.sign_data("aid:1", "test data")
        assert sig is not None

    def test_external_wallet(self):
        wallet = ExternalWalletStorage()
        wallet.store_key("k1", "private123")
        assert wallet.retrieve_key("k1") == "private123"
        sig = wallet.sign_with_key("k1", "hello")
        assert sig is not None
        wallet.delete_key("k1")
        assert wallet.retrieve_key("k1") is None


# ============================================================================
# Credentials tests
# ============================================================================

class TestCredentials:
    def _setup_identity(self, role_config):
        n = KERINode.create(role_config)
        aid = n.create_identity()
        return n, aid

    def test_issue_and_verify(self, role_config):
        node, aid = self._setup_identity(role_config)
        node.schema_manager.register_schema(ACDCSchema(
            schema_id="s:test", name="Test", version="1.0",
            fields={"name": {"required": True}},
        ))
        cred = node.credential_issuer.issue(aid, aid, "s:test", {"name": "Alice"})
        assert node.credential_verifier.verify(cred.credential_id)

    def test_revoked_credential_fails_verification(self, role_config):
        node, aid = self._setup_identity(role_config)
        node.schema_manager.register_schema(ACDCSchema(
            schema_id="s:test", name="Test", version="1.0",
            fields={"name": {"required": True}},
        ))
        cred = node.credential_issuer.issue(aid, aid, "s:test", {"name": "Bob"})
        node.revocation_cache.revoke(cred.credential_id)
        assert not node.credential_verifier.verify(cred.credential_id)

    def test_missing_required_field_raises(self, role_config):
        node, aid = self._setup_identity(role_config)
        node.schema_manager.register_schema(ACDCSchema(
            schema_id="s:strict", name="Strict", version="1.0",
            fields={"name": {"required": True}},
        ))
        with pytest.raises(CredentialError):
            node.credential_issuer.issue(aid, aid, "s:strict", {})

    def test_unknown_schema_raises(self, role_config):
        node, aid = self._setup_identity(role_config)
        with pytest.raises(CredentialError):
            node.credential_issuer.issue(aid, aid, "s:unknown", {"x": 1})


# ============================================================================
# Trust / Decision Engine tests
# ============================================================================

class TestTrustEngine:
    def test_known_sender_allowed(self, role_config):
        node = KERINode.create(role_config)
        aid = node.create_identity()
        msg = Message(sender_aid=aid, payload={"action": "test"})
        assert node.trust_guard.is_allowed(msg)

    def test_unknown_sender_rejected(self, role_config):
        node = KERINode.create(role_config)
        msg = Message(sender_aid="unknown:aid", payload={})
        assert not node.trust_guard.is_allowed(msg)


# ============================================================================
# Evidence tests
# ============================================================================

class TestEvidence:
    def test_pipeline(self):
        pipeline = EvidencePipeline(
            EvidenceBuilder(),
            EvidenceHasher(),
            EvidenceHashSigner(),
            EvidenceStoreAPI(),
        )
        msg = Message(sender_aid="aid:1", payload={"data": "test"})
        evidence = pipeline.process(msg)
        assert evidence.hash_value is not None
        assert evidence.signature is not None

    def test_evidence_store(self):
        builder = EvidenceBuilder()
        hasher = EvidenceHasher()
        store = EvidenceStoreAPI()
        msg = Message(sender_aid="aid:1", payload={})
        ev = builder.build(msg)
        hasher.hash(ev)
        store.save(ev)
        assert store.get(ev.evidence_id) is not None
        results = store.get_for_message(msg.message_id)
        assert len(results) == 1

    def test_unhashed_evidence_not_storable(self):
        store = EvidenceStoreAPI()
        ev = Evidence(message_id="m1", raw_data={"x": 1})
        from keri.core import EvidenceError
        with pytest.raises(EvidenceError):
            store.save(ev)


# ============================================================================
# Output tests
# ============================================================================

class TestOutput:
    def test_output_pipeline(self):
        q = OutputQueue()
        signer = OutputSigner("test_private_key")
        manager = OutputManager(q, signer)
        collector = OutputCollector(q)

        received = []
        collector.register_handler(lambda e: received.append(e))

        msg = Message(sender_aid="aid:1", payload={"result": "ok"})
        env = manager.submit(msg, sender_aid="aid:1")
        assert env.signature is not None

        collected = collector.collect_all()
        assert len(collected) == 1
        assert len(received) == 1


# ============================================================================
# Full end-to-end tests
# ============================================================================

class TestEndToEnd:
    def test_full_pipeline(self, role_config):
        node = KERINode.create(role_config)
        aid = node.create_identity()

        node.schema_manager.register_schema(ACDCSchema(
            schema_id="urn:test:cred",
            name="Test Credential",
            version="1.0",
            fields={"role": {"required": True}},
        ))
        cred = node.credential_issuer.issue(
            issuer_aid=aid, subject_aid=aid,
            schema_id="urn:test:cred",
            claims={"role": "admin"},
        )

        node.ingest({
            "id": "msg-001",
            "sender": aid,
            "payload": {"action": "admin_action"},
            "credentials": [cred.credential_id],
        })

        envelope = node.process()
        assert envelope is not None
        assert envelope.payload.get("allowed") is True

    def test_multiple_identities(self, role_config):
        node = KERINode.create(role_config)
        aids = [node.create_identity(seed=f"seed_{i}") for i in range(3)]
        assert len(set(aids)) == 3
        for aid in aids:
            state = node.identity_api.resolve_aid(aid)
            assert state is not None

    def test_output_handler(self, role_config):
        node = KERINode.create(role_config)
        aid = node.create_identity()

        outputs = []
        node.register_output_handler(outputs.append)

        node.ingest({"sender": aid, "payload": {"ping": True}})
        node.process()
        node.collect_outputs()
        assert len(outputs) == 1

    def test_delegation_chain(self, role_config):
        node = KERINode.create(role_config)
        root_aid = node.create_identity(seed="root")
        child_aid = node.create_identity(seed="child", delegator_aid=root_aid)

        chain = node.credential_verifier._delegation.resolve_delegation_chain(child_aid)
        assert root_aid in chain
        assert child_aid in chain
