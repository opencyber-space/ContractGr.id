from typing import Dict, Any, List, Tuple, Union

from .schema import *
from .db import *
from .parser import ContractSpecParser


class ContractManager:
    def __init__(self, contract_db, sub_contract_db, action_db, verification_db, constraint_db):
        self.contract_db = contract_db
        self.sub_contract_db = sub_contract_db
        self.action_db = action_db
        self.verification_db = verification_db
        self.constraint_db = constraint_db

    def create(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        parser = ContractSpecParser()
        parsed = parser.parse(spec)

        result = {}
        result['contract'] = self.contract_db.insert(Contract.from_dict(parsed.contract))
        result['sub_contracts'] = [self.sub_contract_db.insert(SubContract.from_dict(sc)) for sc in parsed.sub_contracts]
        result['actions'] = [self.action_db.insert(Action.from_dict(a)) for a in parsed.actions]
        result['verification_entries'] = [self.verification_db.insert(VerificationEntry.from_dict(v)) for v in parsed.verification_entries]
        result['constraints'] = [self.constraint_db.insert(SubContractConstraint.from_dict(c)) for c in parsed.constraints]
        return result

    def update(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        parser = ContractSpecParser()
        parsed = parser.parse(spec)

        result = {}
        result['contract'] = self.contract_db.update(parsed.contract["contract_id"], "contract_id", parsed.contract)
        result['sub_contracts'] = [self.sub_contract_db.update(sc["sub_contract_id"], "sub_contract_id", sc) for sc in parsed.sub_contracts]
        result['actions'] = [self.action_db.update(a["action_id"], "action_id", a) for a in parsed.actions]
        result['verification_entries'] = [self.verification_db.update(v["verification_entry_id"], "verification_entry_id", v) for v in parsed.verification_entries]
        result['constraints'] = [self.constraint_db.update(c["constraint_id"], "constraint_id", c) for c in parsed.constraints]
        return result

    def delete(self, contract_id: str) -> Dict[str, Any]:
        result = {}
        result['contract'] = self.contract_db.delete(contract_id, "contract_id")

        sub_contracts_ok, sub_contracts = self.sub_contract_db.query({"contract_id": contract_id})
        if not sub_contracts_ok:
            sub_contracts = []
        sub_contract_ids = [sc["sub_contract_id"] for sc in sub_contracts]

        result['sub_contracts'] = [self.sub_contract_db.delete(sid, "sub_contract_id") for sid in sub_contract_ids]

        sub_clause_ids = []
        for sc in sub_contracts:
            clause_data = sc.get("sub_contract_clause_data")
            if isinstance(clause_data, dict):
                sub_clause_id = clause_data.get("sub_clause_id")
                if sub_clause_id:
                    sub_clause_ids.append(sub_clause_id)

        actions_ok, actions = self.action_db.query({"sub_clause_id": {"$in": sub_clause_ids}})
        result['actions'] = [self.action_db.delete(a["action_id"], "action_id") for a in (actions if actions_ok else [])]

        verifications_ok, verifications = self.verification_db.query({"sub_clause_id": {"$in": sub_clause_ids}})
        result['verification_entries'] = [self.verification_db.delete(v["verification_entry_id"], "verification_entry_id") for v in (verifications if verifications_ok else [])]

        constraints_ok, constraints = self.constraint_db.query({"sub_clause_id": {"$in": sub_clause_ids}})
        result['constraints'] = [self.constraint_db.delete(c["constraint_id"], "constraint_id") for c in (constraints if constraints_ok else [])]

        return result

    def delete_sub_document(self, doc_type: str, doc_id: str) -> Union[Tuple[bool, str], Tuple[bool, int]]:
        db_map = {
            "sub_contract": (self.sub_contract_db, "sub_contract_id"),
            "action": (self.action_db, "action_id"),
            "verification_entry": (self.verification_db, "verification_entry_id"),
            "constraint": (self.constraint_db, "constraint_id")
        }
        if doc_type not in db_map:
            return False, f"Unsupported doc_type {doc_type}"

        db, id_field = db_map[doc_type]
        return db.delete(doc_id, id_field)
