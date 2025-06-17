import os
import logging
from pymongo import MongoClient, errors
from typing import Dict, Any, Tuple, Union, List

from .schema import *

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class BaseMongoCRUD:
    def __init__(self, db_name: str, collection_name: str):
        try:
            uri = os.getenv("MONGO_URL", "mongodb://localhost:27017")
            self.client = MongoClient(uri)
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            logger.info(f"MongoDB connection established for {collection_name}")
        except errors.ConnectionFailure as e:
            logger.error(f"Could not connect to MongoDB: {e}")
            raise

    def insert(self, obj) -> Tuple[bool, Union[str, Any]]:
        try:
            result = self.collection.insert_one(obj.to_dict())
            return True, result.inserted_id
        except errors.PyMongoError as e:
            logger.error(f"Insert error: {e}")
            return False, str(e)

    def update(self, obj_id: str, id_field: str, update_fields: Dict[str, Any]) -> Tuple[bool, Union[str, int]]:
        try:
            result = self.collection.update_one({id_field: obj_id}, {"$set": update_fields}, upsert=True)
            return (True, result.modified_count) if result.modified_count > 0 else (False, "No document updated")
        except errors.PyMongoError as e:
            logger.error(f"Update error: {e}")
            return False, str(e)

    def delete(self, obj_id: str, id_field: str) -> Tuple[bool, Union[str, int]]:
        try:
            result = self.collection.delete_one({id_field: obj_id})
            return (True, result.deleted_count) if result.deleted_count > 0 else (False, "No document deleted")
        except errors.PyMongoError as e:
            logger.error(f"Delete error: {e}")
            return False, str(e)

    def get_by_id(self, obj_id: str, id_field: str, model_class) -> Tuple[bool, Union[str, Any]]:
        try:
            doc = self.collection.find_one({id_field: obj_id})
            if doc:
                doc.pop("_id", None)
                return True, model_class.from_dict(doc)
            return False, "No document found"
        except errors.PyMongoError as e:
            logger.error(f"Get error: {e}")
            return False, str(e)

    def query(self, query_filter: Dict[str, Any]) -> Tuple[bool, Union[str, List[Dict[str, Any]]]]:
        try:
            docs = list(self.collection.find(query_filter))
            for d in docs:
                d.pop("_id", None)
            return True, docs
        except errors.PyMongoError as e:
            logger.error(f"Query error: {e}")
            return False, str(e)

class ContractDB(BaseMongoCRUD):
    def __init__(self):
        super().__init__("contracts_db", "contracts")

    def get_contract(self, contract_id: str) -> Tuple[bool, Union[str, Contract]]:
        return self.get_by_id(contract_id, "contract_id", Contract)


class SubContractDB(BaseMongoCRUD):
    def __init__(self):
        super().__init__("contracts_db", "sub_contracts")

    def get_sub_contract(self, sub_contract_id: str) -> Tuple[bool, Union[str, SubContract]]:
        return self.get_by_id(sub_contract_id, "sub_contract_id", SubContract)

class VerificationEntryDB(BaseMongoCRUD):
    def __init__(self):
        super().__init__("contracts_db", "verification_entries")

    def get_verification_entry(self, verification_entry_id: str) -> Tuple[bool, Union[str, VerificationEntry]]:
        return self.get_by_id(verification_entry_id, "verification_entry_id", VerificationEntry)


class ActionDB(BaseMongoCRUD):
    def __init__(self):
        super().__init__("contracts_db", "actions")

    def get_action(self, action_id: str) -> Tuple[bool, Union[str, Action]]:
        return self.get_by_id(action_id, "action_id", Action)


class SubContractConstraintDB(BaseMongoCRUD):
    def __init__(self):
        super().__init__("contracts_db", "sub_contract_constraints")

    def get_constraint(self, constraint_id: str) -> Tuple[bool, Union[str, SubContractConstraint]]:
        return self.get_by_id(constraint_id, "constraint_id", SubContractConstraint)
