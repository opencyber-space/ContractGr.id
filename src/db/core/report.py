from typing import Dict, Any, List, Tuple, Union
from dataclasses import dataclass

from .schema import Contract


class ContractReportGenerator:
    def __init__(self, contract_db, sub_contract_db, action_db, verification_db, constraint_db):
        self.contract_db = contract_db
        self.sub_contract_db = sub_contract_db
        self.action_db = action_db
        self.verification_db = verification_db
        self.constraint_db = constraint_db

    def generate_report(self, contract_id: str) -> Tuple[bool, Union[str, Dict[str, Any]]]:
        try:
            # Fetch contract
            success, contract = self.contract_db.get_by_id(contract_id, "contract_id", Contract)
            if not success:
                return False, f"Contract with ID '{contract_id}' not found."

            # Fetch sub-contracts
            sub_contracts_success, sub_contracts = self.sub_contract_db.query({"contract_id": contract_id})
            sub_contracts = sub_contracts if sub_contracts_success else []

            # Collect sub_clause_ids
            sub_clause_ids = []
            for sc in sub_contracts:
                clause_data = sc.get("sub_contract_clause_data")
                if isinstance(clause_data, list):
                    for clause in clause_data:
                        sub_clause_id = clause.get("sub_clause_id")
                        if sub_clause_id:
                            sub_clause_ids.append(sub_clause_id)

            # Fetch related documents
            actions_success, actions = self.action_db.query({"sub_clause_id": {"$in": sub_clause_ids}})
            actions = actions if actions_success else []

            verifications_success, verifications = self.verification_db.query({"sub_clause_id": {"$in": sub_clause_ids}})
            verifications = verifications if verifications_success else []

            constraints_success, constraints = self.constraint_db.query({"sub_clause_id": {"$in": sub_clause_ids}})
            constraints = constraints if constraints_success else []

            # Combine everything
            full_spec = {
                "contract": contract.to_dict(),
                "sub_contracts": sub_contracts,
                "actions": actions,
                "verification_entries": verifications,
                "constraints": constraints
            }

            return True, full_spec

        except Exception as e:
            return False, str(e)
