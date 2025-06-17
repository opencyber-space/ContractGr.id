from .db import *
from dsl_executor import new_dsl_workflow_executor, parse_dsl_output

from .comm import NATSClient

from typing import Dict


import asyncio
import json
import logging
from nats.aio.client import Client as NATS
from typing import Dict


class NATSClient:
    def __init__(self, servers: str = "nats://localhost:4222"):
        self.servers = servers
        self.nc = NATS()
        self.connected = False
        self.logger = logging.getLogger("NATSClient")

    async def connect(self):
        if not self.connected:
            try:
                await self.nc.connect(servers=[self.servers])
                self.connected = True
                self.logger.info(f"Connected to NATS at {self.servers}")
            except Exception as e:
                self.logger.error(f"Failed to connect to NATS: {e}")
                raise

    async def _publish_async(self, subject: str, message: Dict):
        try:
            await self.connect()
            payload = json.dumps(message).encode()
            await self.nc.publish(subject, payload)
            self.logger.info(f"Published message to {subject}")
        except Exception as e:
            self.logger.error(f"Error publishing to {subject}: {e}")

    def publish(self, subject: str, message: Dict):
        asyncio.run(self._publish_async(subject, message))


def execute_pqt(pqt_dsl: str, context: Dict[str, Any]) -> bool:
    try:
        # Restrict built-ins for security
        allowed_globals = {
            "event_data": context.get("event_data", {}),
            "sub_contract": context.get("sub_contract", {})
        }

        result = eval(pqt_dsl, allowed_globals)
        if not isinstance(result, bool):
            raise ValueError("PQT expression must return a boolean.")

        return result
    except Exception as e:
        print(f"[PQT Error] {e}")
        return False

def perform_verification(
    verification_id: str,
    sender_subject_id: str,
    event_data: Dict[str, Any],
    sub_contract_document: Dict[str, Any],
    verification_db,
    action_db,
    sub_contract_db,
    nats_client
) -> Dict[str, Any]:
    try:
        success, verification = verification_db.get_by_id(verification_id, "verification_entry_id", None)
        if not success:
            return {"success": False, "error": f"Verification entry {verification_id} not found."}

        executor = new_dsl_workflow_executor(
            workflow_id=verification["verification_dsl_workflow_id"],
            workflows_base_uri=os.getenv("WORKFLOWS_API_URL", "http://workflow-registry"),
            is_remote=False,
            addons={"verification_config": verification.get("verification_config", {})}
        )

        input_data = {"event_data": event_data, "sub_contract": sub_contract_document}
        raw_output = executor.execute(input_data)
        output = parse_dsl_output(raw_output)

        result = {"verified": True, "data": output}

        if "verification_outcome_action_id" in verification and verification["verification_outcome_action_id"]:
            action_id = verification["verification_outcome_action_id"]
            execute_action(action_id, sender_subject_id, output, sub_contract_document)
        else:
            sub_contract_id = sub_contract_document["sub_contract_id"]
            update_success, _ = sub_contract_db.update(sub_contract_id, "sub_contract_id", {
                "sub_contract_status": "fulfilled"
            })
    
            if not update_success:
                return {"success": False, "error": "Failed to update sub-contract to fulfilled"}

            message = {
                "event_type": "sub_contract_fullfilled",
                "sender_subject_id": sender_subject_id,
                "event_data": {
                    "sub_contract_data": sub_contract_document,
                    "verification_data": output
                }
            }

            involved_subjects = sub_contract_document.get("sub_contract_parties_ids", [])
            for subject_id in involved_subjects:
                topic = f"{subject_id}__events"
                nats_client.publish(topic, message)

        return {"success": True, "result": result}

    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_action(
    action_id: str,
    sender_subject_id: str,
    event_data: Dict[str, Any],
    sub_contract_document: Dict[str, Any],
    action_db
) -> Dict[str, Any]:
    try:
        # Step 1: Fetch the action
        success, action = action_db.get_by_id(action_id, "action_id", None)
        if not success:
            return {"success": False, "error": f"Action {action_id} not found."}

        # Step 2: Execute PQT if present
        pqt_dsl = action.get("action_execution_ppt_dsl")
        if pqt_dsl:
            passed = execute_pqt(pqt_dsl, {
                "event_data": event_data,
                "sub_contract": sub_contract_document
            })

            if not passed:
                return {"success": False, "error": "PQT condition failed."}

        # Step 3: Execute fulfillment DSL
        executor = new_dsl_workflow_executor(
            workflow_id=action["action_fulfillment_dsl_workflow_id"],
            workflows_base_uri=os.getenv("WORKFLOWS_API_URL", "http://workflow-registry"),
            is_remote=False,
            addons={"execution_config": action.get("action_execution_config", {})}
        )

        input_data = {
            "event_data": event_data,
            "sub_contract": sub_contract_document
        }

        raw_output = executor.execute(input_data)
        output = parse_dsl_output(raw_output)

        return {"success": True, "result": {"executed": True, "output": output}}

    except Exception as e:
        return {"success": False, "error": str(e)}


class SubContractUtils:
    def __init__(self, sub_contract_db, verification_db, action_db, nats_client):
        self.sub_contract_db = sub_contract_db
        self.verification_db = verification_db
        self.action_db = action_db
        self.nats = nats_client
        self.logger = logging.getLogger("sub_contract_utils")

    def push_event_to_subjects(self, subject_ids: List[str], message: Dict[str, Any]):
        for subject_id in subject_ids:
            topic = f"{subject_id}__events"
            self.nats.publish(topic, message)
            self.logger.info(f"Published message to {topic}: {message}")

    def invoke_sub_contract_update(
        self,
        sub_contract_id: str,
        event_type: str,
        event_data: Dict[str, Any],
        sender_subject_id: str
    ) -> Dict[str, Any]:
        # Step 1: Fetch sub-contract
        success, sub_contract = self.sub_contract_db.get_by_id(sub_contract_id, "sub_contract_id", None)
        if not success:
            return {"success": False, "error": f"SubContract with ID {sub_contract_id} not found."}

        # Step 2: Check if sender is a valid subject
        valid_subjects = sub_contract.get("sub_contract_parties_ids", [])
        if sender_subject_id not in valid_subjects:
            return {"success": False, "error": "Sender not authorized for this sub-contract."}

        # Step 3: Check verification map
        verification_map = sub_contract.get("sub_contract_verification_map", {})
        if event_type in verification_map:
            verification_id = verification_map[event_type]
            perform_verification(verification_id, sender_subject_id, event_data, sub_contract)
            return {"success": True, "message": "Verification performed."}

        # Step 4: Check actions map
        actions_map = sub_contract.get("sub_contract_actions_map", {})
        if event_type in actions_map:
            action_id = actions_map[event_type]
            execute_action(action_id, sender_subject_id, event_data, sub_contract)
            return {"success": True, "message": "Action executed."}

        # Step 5: Fulfill the contract
        update_result = self.sub_contract_db.update(
            sub_contract_id, "sub_contract_id", {"sub_contract_status": "fulfilled"}
        )
        if not update_result[0]:
            return {"success": False, "error": "Failed to update sub-contract status."}

        message = {
            "event_type": "sub_contract_fullfilled",
            "sender_subject_id": sender_subject_id,
            "event_data": sub_contract
        }
        self.push_event_to_subjects(valid_subjects, message)

        return {"success": True, "message": "Sub-contract fulfilled and event pushed."}