from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class ParsedContractSpec:
    contract: Dict[str, Any]
    sub_contracts: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    verification_entries: List[Dict[str, Any]]
    constraints: List[Dict[str, Any]]


class ContractSpecParser:
    def validate_contract(self, contract: Dict[str, Any]):
        required_fields = [
            "contract_id", "contract_type", "contract_parties_ids",
            "contract_status", "contract_creation_time"
        ]
        for field in required_fields:
            if field not in contract:
                raise ValueError(f"Missing required field in contract: '{field}'")

    def validate_sub_contract(self, sub_contract: Dict[str, Any]):
        required_fields = ["sub_contract_id", "contract_id", "sub_contract_status"]
        for field in required_fields:
            if field not in sub_contract:
                raise ValueError(f"Missing required field in sub_contract: '{field}'")

    def validate_action(self, action: Dict[str, Any]):
        required_fields = ["action_id", "sub_clause_id", "action_type"]
        for field in required_fields:
            if field not in action:
                raise ValueError(f"Missing required field in action: '{field}'")

    def validate_verification_entry(self, entry: Dict[str, Any]):
        required_fields = ["verification_entry_id", "sub_clause_id", "verification_status"]
        for field in required_fields:
            if field not in entry:
                raise ValueError(f"Missing required field in verification_entry: '{field}'")

    def validate_constraint(self, constraint: Dict[str, Any]):
        required_fields = ["constraint_id", "sub_clause_id", "constraint_type"]
        for field in required_fields:
            if field not in constraint:
                raise ValueError(f"Missing required field in constraint: '{field}'")

    def parse(self, spec: Dict[str, Any]) -> ParsedContractSpec:
        if "contract" not in spec:
            raise ValueError("Missing top-level 'contract' section in spec.")

        contract = spec["contract"]
        self.validate_contract(contract)

        sub_contracts = spec.get("sub_contracts", [])
        for sc in sub_contracts:
            self.validate_sub_contract(sc)

        actions = spec.get("actions", [])
        for a in actions:
            self.validate_action(a)

        verifications = spec.get("verification_entries", [])
        for v in verifications:
            self.validate_verification_entry(v)

        constraints = spec.get("constraints", [])
        for c in constraints:
            self.validate_constraint(c)

        return ParsedContractSpec(
            contract=contract,
            sub_contracts=sub_contracts,
            actions=actions,
            verification_entries=verifications,
            constraints=constraints
        )
