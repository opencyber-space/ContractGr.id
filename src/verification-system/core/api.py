from flask import Flask, request, jsonify
from .actions import perform_verification  
from .db import VerificationEntryDB, SubContractDB, ActionDB
from .comm import NATSClient  

app = Flask(__name__)

@app.route("/verification/<verification_id>", methods=["POST"])
def trigger_verification(verification_id):
    try:
        data = request.json
        required_fields = ["sender_subject_id", "event_data", "sub_contract_document"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "message": f"Missing field: {field}"}), 200

        result = perform_verification(
            verification_id=verification_id,
            sender_subject_id=data["sender_subject_id"],
            event_data=data["event_data"],
            sub_contract_document=data["sub_contract_document"],
            verification_db=VerificationEntryDB(),
            action_db=ActionDB(),
            sub_contract_db=SubContractDB(),
            nats_client=NATSClient()
        )

        if not result.get("success"):
            return jsonify({"success": False, "message": result.get("error", "Verification failed")}), 200

        return jsonify({"success": True, "data": result["result"]}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 200


def run_api_server():
    app.run(host='0.0.0.0', port=8000)