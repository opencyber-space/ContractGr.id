"""
Key Management System (KMS)
============================
Implements:
  - HotKeysCache        : in-memory cache of currently active signing keys
  - PreRotatedKeysSaver : stores pre-rotation key commitments
  - RecoveryKeysManager : manages recovery key material
  - KeyVault            : facade for key storage (internal or external)
  - ExternalWalletStorage : stub for external wallet backend
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..core.models import KeyPair
from ..core.crypto import generate_key_pair, derive_next_key_digest, sign
from ..core.exceptions import KERIError


# ---------------------------------------------------------------------------
# External wallet storage stub
# ---------------------------------------------------------------------------

class ExternalWalletStorage:
    """
    Stub for an external wallet backend (HSM, hardware wallet, etc.).
    In production, implement the interface against a real wallet SDK.
    """

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}  # key_id -> private_key

    def store_key(self, key_id: str, private_key: str) -> None:
        self._store[key_id] = private_key

    def retrieve_key(self, key_id: str) -> Optional[str]:
        return self._store.get(key_id)

    def delete_key(self, key_id: str) -> None:
        self._store.pop(key_id, None)

    def sign_with_key(self, key_id: str, data: str) -> Optional[str]:
        pk = self.retrieve_key(key_id)
        if not pk:
            return None
        return sign(data, pk)


# ---------------------------------------------------------------------------
# Hot Keys Cache
# ---------------------------------------------------------------------------

class HotKeysCache:
    """
    Caches currently-active (hot) signing key pairs in memory.
    These are the keys used for immediate signing operations.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, KeyPair] = {}  # aid -> KeyPair

    def put(self, aid: str, key_pair: KeyPair) -> None:
        self._cache[aid] = key_pair

    def get(self, aid: str) -> Optional[KeyPair]:
        return self._cache.get(aid)

    def remove(self, aid: str) -> None:
        self._cache.pop(aid, None)

    def list_aids(self) -> List[str]:
        return list(self._cache.keys())


# ---------------------------------------------------------------------------
# Pre-rotated Keys Saver
# ---------------------------------------------------------------------------

@dataclass
class PreRotationEntry:
    aid: str
    next_public_key: str
    next_key_digest: str
    created_at: float = field(default_factory=time.time)


class PreRotatedKeysSaver:
    """
    Saves pre-rotation key pairs — the keys committed to in the current KEL event
    but not yet active. On rotation they become the new hot keys.
    """

    def __init__(self, wallet: Optional[ExternalWalletStorage] = None) -> None:
        self._entries: Dict[str, PreRotationEntry] = {}
        self._wallet = wallet

    def save(self, aid: str, pre_rotation_key_pair: KeyPair) -> PreRotationEntry:
        digest = derive_next_key_digest(pre_rotation_key_pair.public_key)
        entry = PreRotationEntry(
            aid=aid,
            next_public_key=pre_rotation_key_pair.public_key,
            next_key_digest=digest,
        )
        self._entries[aid] = entry
        # Optionally persist private key to external wallet
        if self._wallet:
            self._wallet.store_key(f"prerot:{aid}", pre_rotation_key_pair.private_key)
        return entry

    def get(self, aid: str) -> Optional[PreRotationEntry]:
        return self._entries.get(aid)

    def promote_to_hot(self, aid: str) -> Optional[KeyPair]:
        """After a rotation event, return the pre-rotated key pair as the new hot key."""
        entry = self._entries.get(aid)
        if not entry:
            return None
        # In production, retrieve from secure storage; here we stub with public key only
        private_key = ""
        if self._wallet:
            private_key = self._wallet.retrieve_key(f"prerot:{aid}") or ""
        return KeyPair(
            public_key=entry.next_public_key,
            private_key=private_key,
        )


# ---------------------------------------------------------------------------
# Recovery Keys Manager
# ---------------------------------------------------------------------------

class RecoveryKeysManager:
    """
    Manages recovery key material for disaster recovery scenarios.
    Can optionally use ExternalWalletStorage as backend.
    """

    def __init__(self, wallet: Optional[ExternalWalletStorage] = None) -> None:
        self._recovery_keys: Dict[str, List[str]] = {}  # aid -> [public_keys]
        self._wallet = wallet

    def register_recovery_keys(self, aid: str, key_pairs: List[KeyPair]) -> None:
        pub_keys = [kp.public_key for kp in key_pairs]
        self._recovery_keys[aid] = pub_keys
        if self._wallet:
            for i, kp in enumerate(key_pairs):
                self._wallet.store_key(f"recovery:{aid}:{i}", kp.private_key)

    def get_recovery_keys(self, aid: str) -> List[str]:
        return list(self._recovery_keys.get(aid, []))

    def has_recovery_keys(self, aid: str) -> bool:
        return aid in self._recovery_keys and len(self._recovery_keys[aid]) > 0


# ---------------------------------------------------------------------------
# Key Vault (external API façade)
# ---------------------------------------------------------------------------

class KeyVault:
    """
    Key Vault (external API) — façade over all key stores.
    Corresponds to 'Key Valut (external API)' in the diagram.
    KMS features can use external wallet as backend if supported.
    """

    def __init__(
        self,
        hot_keys: HotKeysCache,
        pre_rotation: PreRotatedKeysSaver,
        recovery: RecoveryKeysManager,
        external_wallet: Optional[ExternalWalletStorage] = None,
        use_external_storage: bool = False,
    ) -> None:
        self.hot_keys = hot_keys
        self.pre_rotation = pre_rotation
        self.recovery = recovery
        self.external_wallet = external_wallet
        self.use_external_storage = use_external_storage

    def generate_and_store_key_pair(self, aid: str, seed: Optional[str] = None) -> KeyPair:
        """Generate a new key pair and store as hot key."""
        pub, priv = generate_key_pair(seed)
        kp = KeyPair(public_key=pub, private_key=priv)
        self.hot_keys.put(aid, kp)
        if self.use_external_storage and self.external_wallet:
            self.external_wallet.store_key(f"hot:{aid}", priv)
        return kp

    def sign_data(self, aid: str, data: str) -> Optional[str]:
        """Sign data using the hot key for the given AID."""
        kp = self.hot_keys.get(aid)
        if kp and kp.private_key:
            return sign(data, kp.private_key)
        if self.use_external_storage and self.external_wallet:
            return self.external_wallet.sign_with_key(f"hot:{aid}", data)
        return None

    def rotate_keys(self, aid: str) -> Optional[KeyPair]:
        """
        Promote pre-rotation keys to hot keys after a rotation event.
        Returns the new hot key pair.
        """
        new_hot = self.pre_rotation.promote_to_hot(aid)
        if new_hot:
            self.hot_keys.put(aid, new_hot)
        return new_hot
