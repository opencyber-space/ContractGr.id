from flask import Flask, request, jsonify
import logging

from .controller import ContractManager
from .db import *

from .report import ContractReportGenerator

app = Flask(__name__)
logger = logging.getLogger("contract_api")
logging.basicConfig(level=logging.INFO)


manager = ContractManager(
    ContractDB(),
    SubContractDB(),
    ActionDB(),
    VerificationEntryDB(),
    SubContractConstraintDB()
)

report_generator = ContractReportGenerator(
    ContractDB(),
    SubContractDB(),
    ActionDB(),
    VerificationEntryDB(),
    SubContractConstraintDB()
)

contract_db = ContractDB()
sub_contract_db = SubContractDB()
verification_entry_db = VerificationEntryDB()
action_db = ActionDB()
constraint_db = SubContractConstraintDB()


@app.route('/contract', methods=['POST'])
def create_contract():
    try:
        spec = request.json
        result = manager.create(spec)
        return jsonify({"success": True, "message": "Contract created successfully", "result": result}), 201
    except Exception as e:
        logger.error(f"Error in create_contract: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contract', methods=['PUT'])
def update_contract():
    try:
        spec = request.json
        result = manager.update(spec)
        return jsonify({"success": True, "message": "Contract updated successfully", "result": result}), 200
    except Exception as e:
        logger.error(f"Error in update_contract: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contract/<contract_id>', methods=['DELETE'])
def delete_contract(contract_id):
    try:
        result = manager.delete(contract_id)
        return jsonify({"success": True, "message": "Contract and subdocuments deleted", "result": result}), 200
    except Exception as e:
        logger.error(f"Error in delete_contract: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contract/subdocument/<doc_type>/<doc_id>', methods=['DELETE'])
def delete_sub_document(doc_type, doc_id):
    try:
        success, result = manager.delete_sub_document(doc_type, doc_id)
        if success:
            return jsonify({"success": True, "message": f"{doc_type} deleted", "result": result}), 200
        else:
            return jsonify({"success": False, "error": result}), 404
    except Exception as e:
        logger.error(f"Error in delete_sub_document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contract/<contract_id>/report', methods=['GET'])
def get_contract_report(contract_id):
    try:
        success, report = report_generator.generate_report(contract_id)
        if success:
            return jsonify({"success": True, "data": report}), 200
        else:
            return jsonify({"success": False, "error": report}), 404
    except Exception as e:
        logger.error(f"Error generating contract report: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contract/<contract_id>', methods=['GET'])
def get_contract(contract_id):
    try:
        success, result = contract_db.get_contract(contract_id)
        if success:
            return jsonify({"success": True, "data": result.to_dict()})
        return jsonify({"success": False, "error": result}), 404
    except Exception as e:
        logger.error(f"Error in get_contract: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/sub_contract/<sub_contract_id>', methods=['GET'])
def get_sub_contract(sub_contract_id):
    try:
        success, result = sub_contract_db.get_sub_contract(sub_contract_id)
        if success:
            return jsonify({"success": True, "data": result.to_dict()})
        return jsonify({"success": False, "error": result}), 404
    except Exception as e:
        logger.error(f"Error in get_sub_contract: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/verification_entry/<entry_id>', methods=['GET'])
def get_verification_entry(entry_id):
    try:
        success, result = verification_entry_db.get_verification_entry(
            entry_id)
        if success:
            return jsonify({"success": True, "data": result.to_dict()})
        return jsonify({"success": False, "error": result}), 404
    except Exception as e:
        logger.error(f"Error in get_verification_entry: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/action/<action_id>', methods=['GET'])
def get_action(action_id):
    try:
        success, result = action_db.get_action(action_id)
        if success:
            return jsonify({"success": True, "data": result.to_dict()})
        return jsonify({"success": False, "error": result}), 404
    except Exception as e:
        logger.error(f"Error in get_action: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/sub_contract_constraint/<constraint_id>', methods=['GET'])
def get_constraint(constraint_id):
    try:
        success, result = constraint_db.get_constraint(constraint_id)
        if success:
            return jsonify({"success": True, "data": result.to_dict()})
        return jsonify({"success": False, "error": result}), 404
    except Exception as e:
        logger.error(f"Error in get_constraint: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contract/query', methods=['POST'])
def query_contracts():
    try:
        query_filter = request.json
        success, result = contract_db.query(query_filter)
        if success:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": result}), 400
    except Exception as e:
        logger.error(f"Error in query_contracts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/sub_contract/query', methods=['POST'])
def query_sub_contracts():
    try:
        query_filter = request.json
        success, result = sub_contract_db.query(query_filter)
        if success:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": result}), 400
    except Exception as e:
        logger.error(f"Error in query_sub_contracts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/verification_entry/query', methods=['POST'])
def query_verification_entries():
    try:
        query_filter = request.json
        success, result = verification_entry_db.query(query_filter)
        if success:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": result}), 400
    except Exception as e:
        logger.error(f"Error in query_verification_entries: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/action/query', methods=['POST'])
def query_actions():
    try:
        query_filter = request.json
        success, result = action_db.query(query_filter)
        if success:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": result}), 400
    except Exception as e:
        logger.error(f"Error in query_actions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/sub_contract_constraint/query', methods=['POST'])
def query_constraints():
    try:
        query_filter = request.json
        success, result = constraint_db.query(query_filter)
        if success:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": result}), 400
    except Exception as e:
        logger.error(f"Error in query_constraints: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
