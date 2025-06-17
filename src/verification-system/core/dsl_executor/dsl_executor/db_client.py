import requests

class WorkflowsClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def get_workflows(self):
        try:
            response = requests.get(f"{self.base_url}/workflows")
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_workflow(self, workflow_id):
        try:
            response = requests.get(f"{self.base_url}/workflows/{workflow_id}")
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            return {"success": False, "message": str(e)}

    def create_workflow(self, workflow_data):
        try:
            response = requests.post(f"{self.base_url}/workflows", json=workflow_data)
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            return {"success": False, "message": str(e)}

    def update_workflow(self, workflow_id, workflow_data):
        try:
            response = requests.put(f"{self.base_url}/workflows/{workflow_id}", json=workflow_data)
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            return {"success": False, "message": str(e)}

    def delete_workflow(self, workflow_id):
        try:
            response = requests.delete(f"{self.base_url}/workflows/{workflow_id}")
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            return {"success": False, "message": str(e)}

