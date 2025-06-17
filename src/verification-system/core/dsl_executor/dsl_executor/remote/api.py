import requests
from typing import Dict, List, Tuple
from dataclasses import asdict

from .schema import Graph, PolicyRule


def convert_workflow_to_graph_policies(workflow_data: Dict) -> Tuple[Graph, List[PolicyRule]]:

    # Extract workflow details
    workflow_id = workflow_data['workflow_id']
    name = workflow_data['name']
    version = workflow_data['version']['version']
    release_tag = workflow_data['version']['releaseTag']
    description = workflow_data['description']
    tags = workflow_data.get('tags', [])
    graph_metadata = workflow_data.get('globalSettings', {})

    # Extract graph structure
    graph_connection_data = workflow_data.get('graph', {})

    # Convert modules to policy rules
    policies = []
    for module_name, module_data in workflow_data.get('modules', {}).items():
        policy = PolicyRule(
            policy_rule_uri=f"{module_name}:{version}-{release_tag}",
            name=module_name,
            version=version,
            release_tag=release_tag,
            metadata=module_data.get('metadata', {}),
            tags=module_data.get('tags', []),
            code=module_data.get('codePath', ""),
            code_type=module_data.get('codeType', ""),
            type=module_data.get('moduleType', ""),
            policy_input_schema=module_data.get('inputSchema', {}),
            policy_output_schema=module_data.get('outputSchema', {}),
            policy_settings_schema=module_data.get('settingsSchema', {}),
            policy_parameters_schema=module_data.get('parametersSchema', {}),
            policy_settings=module_data.get('settings', {}),
            policy_parameters=module_data.get('parameters', {}),
            description=module_data.get('description', ""),
            functionality_data=module_data.get('functionalityData', {}),
            resource_estimates=module_data.get('resource_requirements', {})
        )
        policies.append(policy)

    # Create Graph object
    graph = Graph(
        graph_uri=f"{name}:{version}-{release_tag}",
        graph_name=name,
        graph_version=version,
        graph_release_tag=release_tag,
        graph_metadata=graph_metadata,
        graph_function_ids=[policy.policy_rule_uri for policy in policies],
        graph_connection_data=graph_connection_data,
        graph_search_tags=tags,
        graph_description=description,
        graph_input_schema=workflow_data.get('graphInputSchema', {}),
        graph_output_schema=workflow_data.get('graphOutputSchema', {}),
    )

    return graph, policies


class GraphAPIClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def estimate_adhoc_graph(self, executor_id, policies):

        url = f"{self.base_url}/graph/estimate-adhoc-graph/{executor_id}"
        payload = {"policies": policies}

        try:
            response = requests.post(url, json=payload)
            return response.json()
        except requests.RequestException as e:
            return {"success": False, "message": str(e)}

    def deploy_adhoc_graph(self, executor_id, graph, policies, deploy_parameters):

        url = f"{self.base_url}/graph/deploy-adhoc-graph/{executor_id}"
        payload = {
            "graph": graph,
            "policies": policies,
            "deploy_parameters": deploy_parameters
        }

        try:
            response = requests.post(url, json=payload)
            return response.json()
        except requests.RequestException as e:
            return {"success": False, "message": str(e)}

    def execute_graph(self, graph_uri: str, input_data: Dict) -> Dict:
        url = f"{self.base_url}/graph/execute_graph"
        response = requests.post(
            url, json={"graph_uri": graph_uri, "input_data": input_data})
        return response.json()
    
    def remove_graph(self, graph_uri: str, executor_id: str):
        url = f"{self.base_url}/graph/execute_graph/{executor_id}"
        response = requests.get(url, params={"graph_uri": graph_uri})
        return response.json()