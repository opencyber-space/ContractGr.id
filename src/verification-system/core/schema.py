from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


@dataclass
class Contract:
    contract_id: str
    contract_type: str
    contract_parties_ids: List[str]
    contract_parent_org_id: str
    contract_acl_data: Dict
    contract_acl: Dict
    contract_sub_clauses_id: List[str]
    contract_status: str
    contract_creation_time: str
    last_update_time: str
    contract_final_completion_timestamp: Optional[str]
    final_verifier_id: Optional[str]
    report_url: Optional[str]
    purpose: Optional[str]
    human_readable_description: Optional[str]
    json_parseable_description: Optional[str]
    contract_parties_roles_mapping: Dict

    @staticmethod
    def from_dict(data: Dict) -> 'Contract':
        return Contract(**data)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SubContract:
    sub_contract_id: str
    contract_id: str
    sub_contract_clause_data: List[Dict]
    sub_contract_json_repr: Dict
    sub_contract_parties_ids: List[str]
    sub_contract_status: str
    sub_contract_actions_map: Dict
    sub_contract_verification_map: Dict
    sub_contract_creation_time: str
    last_update_time: str
    sub_report_url: Optional[str]
    verification_subjects_list: Optional[List[str]]
    purpose: Optional[str]
    json_parseable_description: Optional[str]
    sub_clause_constraints: Optional[List[str]]
    sub_contract_parties_roles_mapping: Optional[Dict]
    human_readable_description: Optional[str]

    @staticmethod
    def from_dict(data: Dict) -> 'SubContract':
        return SubContract(**data)

    def to_dict(self) -> Dict:
        return asdict(self)

@dataclass
class Action:
    action_id: str
    sub_clause_id: str
    action_type: str
    action_fulfillment_dsl_workflow_id: str
    action_execution_status: str
    action_execution_config: Dict
    action_outcome_data: Optional[Dict]
    action_execution_ppt_dsl: Optional[str]
    action_execution_constraint_ids: Optional[List[str]]

    @staticmethod
    def from_dict(data: Dict) -> 'Action':
        return Action(**data)

    def to_dict(self) -> Dict:
        return asdict(self)

@dataclass
class SubContractConstraint:
    constraint_id: str
    sub_clause_id: str
    constraint_type: str
    constraint_sub_type: Optional[str]
    constraint_parameters: Dict
    constraint_policy_id: Optional[str]
    constraint_negotiation_parameters: Optional[Dict]
    group_ids: Optional[List[str]]
    role_ids: Optional[List[str]]
    can_negotiate: Optional[bool] = False

    @staticmethod
    def from_dict(data: Dict) -> 'SubContractConstraint':
        return SubContractConstraint(**data)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class VerificationEntry:
    verification_entry_id: str
    sub_clause_action_type: str
    verifier_subject_id: str
    verifier_subject_type: str
    verification_dsl_workflow_id: str
    verification_mode: str
    verification_config: Dict
    verification_status: str
    verification_outcome_data: Dict
    verification_outcome_action_id: Optional[str]
    verification_timestamp: Optional[str]
    verification_cert_data: Optional[Dict]
    sub_clause_id: str

    @staticmethod
    def from_dict(data: Dict) -> 'VerificationEntry':
        return VerificationEntry(**data)

    def to_dict(self) -> Dict:
        return asdict(self)
