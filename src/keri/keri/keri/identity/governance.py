"""
Governance and Role Configuration
===================================
Implements:
  - RoleConfig            : org/block/instance configuration
  - GenesisPolicyLoader   : loads genesis policy from role config
  - GovernanceRulesLoader : loads thresholds, witnesses, etc.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.models import GenesisPolicy
from ..core.exceptions import PolicyError


@dataclass
class RoleConfig:
    """Top-level role configuration (org / block / instance)."""
    org: str
    block: str
    instance: str
    witness_aids: List[str] = field(default_factory=list)
    signing_threshold: int = 1
    rotation_threshold: int = 1
    custom_rules: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "org": self.org,
            "block": self.block,
            "instance": self.instance,
            "witness_aids": self.witness_aids,
            "signing_threshold": self.signing_threshold,
            "rotation_threshold": self.rotation_threshold,
            "custom_rules": self.custom_rules,
        }


class GenesisPolicyLoader:
    """
    Translates a RoleConfig into a GenesisPolicy (thresholds, witnesses, etc).
    Corresponds to 'Genesis policy loader' in the diagram.
    """

    def load(self, role_config: RoleConfig) -> GenesisPolicy:
        if not role_config.org:
            raise PolicyError("RoleConfig must specify an org")
        return GenesisPolicy(
            policy_id=str(uuid.uuid4()),
            org=role_config.org,
            block=role_config.block,
            instance=role_config.instance,
            thresholds={
                "signing": role_config.signing_threshold,
                "rotation": role_config.rotation_threshold,
            },
            witnesses=list(role_config.witness_aids),
            rules=list(role_config.custom_rules),
        )


class GovernanceRulesLoader:
    """
    Loads governance rules (thresholds, witnesses) from a GenesisPolicy.
    Corresponds to 'Governance rules loader (thresholds, witnesses etc)' in diagram.
    """

    def load_rules(self, policy: GenesisPolicy) -> Dict[str, Any]:
        return {
            "thresholds": policy.thresholds,
            "witnesses": policy.witnesses,
            "rules": policy.rules,
        }

    def validate_policy(self, policy: GenesisPolicy) -> None:
        if policy.thresholds.get("signing", 0) < 1:
            raise PolicyError("Signing threshold must be >= 1")
        if policy.thresholds.get("rotation", 0) < 1:
            raise PolicyError("Rotation threshold must be >= 1")
