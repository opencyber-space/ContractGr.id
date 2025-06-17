import logging
from typing import Dict

from .api import GraphAPIClient, Graph, convert_workflow_to_graph_policies

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RemoteDSLExecutor:
    def __init__(self, base_url: str, executor_id: str, workflow_graph: Dict):
        self.client = GraphAPIClient(base_url)
        self.executor_id = executor_id

        try:
            self.graph, self.policies = convert_workflow_to_graph_policies(
                workflow_graph)
            logger.info(
                "Workflow graph successfully converted to Graph and Policies.")
        except Exception as e:
            logger.error(f"Failed to convert workflow graph: {e}")
            raise ValueError("Invalid workflow graph data.") from e

    def estimate(self) -> Dict:
        try:
            policies_data = [policy.to_dict() for policy in self.policies]
            response = self.client.estimate_adhoc_graph(
                self.executor_id, policies_data)
            logger.info(f"Estimate response: {response}")

            data = response['data']
            if len(data['failed_estimates']) > 0:
                raise Exception('estimate failed')

        except Exception as e:
            logger.error(f"Estimation failed: {e}")
            return {"success": False, "message": str(e)}

    def deploy(self) -> Dict:
        try:
            deployment_data = {
                "graph": self.graph.to_dict(),
                "policies": [policy.to_dict() for policy in self.policies],
                "deploy_parameters": {}  # Add actual deploy parameters if available
            }
            response = self.client.deploy_adhoc_graph(
                self.executor_id, deployment_data)
            logger.info(f"Deployment response: {response}")
            return response["data"]
        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            raise e

    def execute(self, input_data: Dict) -> Dict:
        try:
            if not self.graph.graph_uri:
                raise ValueError(
                    "Graph URI is missing in the workflow graph data.")

            response = self.client.execute_graph(
                self.graph.graph_uri, input_data)
            logger.info(f"Execution response: {response}")
            return response["data"]
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            raise e

    def remove(self):
        self.client.remove_graph(self.graph.graph_uri, self.executor_id)
