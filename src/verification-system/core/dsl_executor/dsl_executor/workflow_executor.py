import logging
from collections import defaultdict, deque
from typing import Dict, Any

from .function_executor import LocalCodeExecutor
from .db_client import WorkflowsClient
from .remote import RemoteDSLExecutor
import os

from abc import ABC

logging.basicConfig(level=logging.INFO)


class DSLWorkflowExecutor(ABC):

    def __init__(self, dsl: Dict[str, Any], addons={}) -> None:
        super().__init__()

    def execute(self, input_data):
        pass

    def estimate(self):
        pass

    def load_modules(self):
        pass


class DSLWorkflowExecutorLocal(DSLWorkflowExecutor):
    def __init__(self, dsl: Dict[str, Any], addons={}):
        self.dsl = dsl
        self.global_settings = dsl.get("globalSettings", {})
        self.global_parameters = dsl.get("globalParameters", {})
        self.global_settings.update(addons)
        self.modules = dsl.get("modules", {})
        self.graph = dsl.get("graph", {})
        self.local_code_executors = {}
        self.execution_order = []
        self.validate_and_sort_graph()
        self.load_modules()

    def estimate(self):
        return True

    def validate_and_sort_graph(self):
        # Validate module keys
        all_graph_keys = set(self.graph.keys())
        all_module_keys = set(self.modules.keys())
        if not all_graph_keys.issubset(all_module_keys):
            raise ValueError(
                f"Graph references undefined module keys: {all_graph_keys - all_module_keys}")

        # Build adjacency list and in-degree map
        adjacency_list = defaultdict(list)
        in_degree = defaultdict(int)

        for source, targets in self.graph.items():
            for target in targets:
                adjacency_list[source].append(target)
                in_degree[target] += 1
                in_degree.setdefault(source, 0)

        # Perform topological sorting to detect cycles
        queue = deque([node for node in in_degree if in_degree[node] == 0])
        visited_count = 0

        while queue:
            current = queue.popleft()
            self.execution_order.append(current)
            visited_count += 1
            for neighbor in adjacency_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(in_degree):
            raise ValueError(
                "The graph contains cycles, which are not allowed.")

    def load_modules(self):
        for module_key, module_info in self.modules.items():
            code_path = module_info["codePath"]
            settings = module_info["settings"]
            parameters = module_info["parameters"]

            executor = LocalCodeExecutor(
                download_url=code_path,
                global_settings=self.global_settings,
                global_parameters=self.global_parameters,
                settings=settings,
                parameters=parameters,
                global_state={}
            )

            executor.init()

            self.local_code_executors[module_key] = executor

    def execute(self, input_data: Dict[str, Any]):
        previous_outputs = {}
        sink_nodes = [node for node in self.graph if not self.graph[node]]
        final_output = None

        for module_key in self.execution_order:
            executor = self.local_code_executors[module_key]
            try:
                logging.info(f"Executing module: {module_key}")
                module_input = input_data.copy()
                module_input["previous_outputs"] = previous_outputs
                output = executor.evaluate(module_input)
                previous_outputs[module_key] = output
                logging.info(f"Output of module {module_key}: {output}")
            except Exception as e:
                logging.error(f"Error in module {module_key}: {e}")
                raise

        sink_node = sink_nodes[0]
        final_output = {
            "output": previous_outputs[sink_node],
            "previous_outputs": previous_outputs
        }
        return final_output


class DSLWorkflowExecutorRemote(DSLWorkflowExecutor):

    def __init__(self, dsl: Dict[str, Any], addons={}, executor_id="") -> None:
        super().__init__(dsl, addons)
        self.remote_executor = RemoteDSLExecutor(
            os.getenv("POLICIES_SYSTEM_URL"),
            executor_id=executor_id,
            workflow_graph=dsl
        )

    def execute(self, input_data):
        try:
            return self.execute(input_data)
        except Exception as e:
            raise e

    def estimate(self):
        try:
            return self.estimate()
        except Exception as e:
            raise e

    def load_modules(self):
        try:
            self.remote_executor.deploy()
        except Exception as e:
            raise e


def new_dsl_workflow_executor(workflow_id: str, workflows_base_uri: str, is_remote=False, addons={}, executor_id="") -> DSLWorkflowExecutor:
    try:

        workflows_db = WorkflowsClient(workflows_base_uri)
        dsl_data = workflows_db.get_workflow(workflow_id)

        if is_remote:
            return DSLWorkflowExecutorRemote(dsl_data, addons, executor_id)

        # initialize
        return DSLWorkflowExecutorLocal(dsl_data, addons=addons)

    except Exception as e:
        raise e


def parse_dsl_output(output: dict, module_name: str = ""):
    if module_name == "":
        return output['output']
    else:
        if module_name not in output['previous_outputs']:
            raise Exception(f"module name {module_name} not found")
        return output['previous_outputs'][module_name]
