# Contract Manager API Documentation

## Introduction

The Contract Manager API provides a structured interface for managing legal contracts and their sub-components, such as sub-contracts, actions, verification entries, and constraints. It supports creation, updating, and deletion of a full contract specification using a single JSON payload. The system is designed for modular extensibility and supports clean sub-document isolation.

---

## Architecture

The **Contracts System** is a distributed, extensible, and event-driven framework for managing digital legal contracts and their lifecycle, including creation, updates, execution, verification, and querying. It supports both REST and GraphQL interfaces for managing nested contract structures such as sub-contracts, actions, constraints, and verification entries.

Designed with modular service boundaries and asynchronous dispatch layers, the system enables contract logic to be enforced via programmable workflows (DSL), SLA metrics, and dynamic verification processes. Real-time updates, validations, and action outcomes are processed through an internal message queue and a routing fabric integrated with Kubernetes and service-level event listeners.

![contracts-system](./images/contracts-system.png)

### 1. Contract Lifecycle Management Service

This subsystem manages the creation, update, and deletion of complete contracts and their nested components using a REST interface. It includes a **spec parser** that converts complex JSON inputs into database-ready entries and routes them to specialized service modules for execution.

#### **Controller**

The primary interface for the contract lifecycle service. It processes incoming REST API requests and routes them to the appropriate internal module (creator, updater, deleter). It also invokes the spec parser and performs initial validation checks.

#### **Spec Parser**

Responsible for decomposing a hierarchical contract JSON into normalized components such as `Contract`, `SubContract`, `Action`, `VerificationEntry`, and `Constraint`. These objects are transformed into formats compatible with database persistence modules.

#### **Creator Module**

Handles the insertion of new contract specifications into the database. This module ensures data integrity and atomicity across nested records during initial contract creation.

#### **Updater Module**

Processes update operations for contracts and their components. It performs version checks and ensures logical consistency when contract data is modified after creation.

#### **Deletion Module**

Responsible for cascading deletion of a contract and all of its sub-components. It ensures that no orphan sub-contracts or actions remain after deletion.

---

### 2. Contract Execution and Verification Engine

This module governs the runtime behavior of sub-contracts, including verification workflows, action execution, SLA evaluations, and real-time response dispatch. It is designed to operate in a decentralized queue-based environment, with per-instance event routing and asynchronous acknowledgement handling.


#### **Action Dispatcher**

Acts as the orchestration hub for sub-contract executions. It processes input events (typically from REST or WebSocket), determines whether a verification or action must be triggered, and dispatches the task accordingly.

#### **Sub-Contract Status Updater**

This component modifies the sub-contract’s status field based on fulfillment conditions defined in the spec. It ensures that each action or verification is correctly reflected in the sub-contract lifecycle.

#### **Verification Subject Notifier**

Sends messages on the internal messaging mesh to notify assigned verifiers (subjects) that a verification is required. These may include users, services, or agent systems.

#### **DSL Workflow Invocation Module**

Executes a programmable workflow (via DSL) associated with an action or verification. The result is evaluated to determine fulfillment or failure.

#### **Verification Result Updater**

Handles the final processing of verification workflows, updating the contract or triggering a follow-up action as dictated by the result.

#### **Action Result Updater**

Performs downstream logic once an action is fulfilled — such as transitioning to the next clause, verifying conditions, or updating the DB.

#### **Adhoc Verification Session Handler**

Allows verifiers to initiate on-demand verification checks, dynamically mapped to contracts that support periodic or event-based assessments.

#### **Report Generator and Delivery**

Generates final reports once all contract actions are complete. Reports are linked to associated subjects and stored via URL references in the DB.

#### **Metrics Webhook Handler**

Evaluates metric-based constraints by integrating with SLA/observability systems. If a contract defines metric conditions, this module verifies compliance.

#### **Acknowledgement System**

Sends completion signals back to the origin subject once verification or action execution is complete.

---

### Contract Queue and Routing Subsystem

This layer enables routing of contract-specific events to the correct processing queue based on the contract session or subject. It integrates with Kubernetes event listeners and maintains dynamic routing tables for distributing contract workloads.

#### **Queue Controller**

Handles queue registration, scaling, and session-to-queue assignments. It also processes REST submissions for new tasks tied to contracts.

#### **Router**

Resolves routing targets based on `subject_id` or `session_id`. It dynamically assigns events to queues and updates the routing map as required.

#### **Routing Table / Queue Map**

A stateful table that maps `session_id` to internal queue identifiers. It is updated by the controller and used by the router for dispatch.

#### **Kubernetes Events Listener**

Watches cluster-level events and updates queue availability. This enables dynamic scaling and worker queue discovery in distributed deployments.

#### **Per-Instance Event Queues**

Each active processing instance maintains a queue for incoming contract events. These queues are fed by the router based on session routing logic.

---

## 4. Contract Query and Report System

### System Overview

This subsystem allows external systems and users to query contracts, sub-documents, and generate compliance reports. It offers both REST and GraphQL interfaces, and supports full contract retrievals as well as filtered sub-queries.

---

### Component Descriptions

#### **Query Controller**

Handles incoming REST and GraphQL queries. It supports filtering, search indexing, and joining of sub-components to return composite responses.

#### **Search and Query System**

Provides high-level search across contract metadata such as status, party ID, type, and creation timestamp. Used for audits and organizational indexing.

#### **Report Generator**

Constructs a downloadable or renderable report of the full contract. Includes execution logs, verification timestamps, and outcomes.

#### **GraphQL Plugin**

Enables flexible, nested querying of contract objects using GraphQL syntax. This allows custom clients to extract specific sub-structures efficiently.

---

## Schema

The complete contract is composed of a top-level `Contract` object and associated sub-components:

### Data Classes

```python
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
```


### **Contract Fields**

| Field                                 | Description                                              |
| ------------------------------------- | -------------------------------------------------------- |
| `contract_id`                         | Unique contract identifier                               |
| `contract_type`                       | Type/category of the contract (e.g. service, employment) |
| `contract_parties_ids`                | List of participating entity IDs                         |
| `contract_parent_org_id`              | Organization under which this contract is made           |
| `contract_acl_data`                   | Raw ACL metadata                                         |
| `contract_acl`                        | Evaluated ACL structure                                  |
| `contract_sub_clauses_id`             | IDs of referenced clauses                                |
| `contract_status`                     | Status such as active, expired, etc.                     |
| `contract_creation_time`              | Time of initial creation (ISO format)                    |
| `last_update_time`                    | Last time contract was updated                           |
| `contract_final_completion_timestamp` | When it was marked as completed                          |
| `final_verifier_id`                   | Who verified the final contract                          |
| `report_url`                          | External report link if available                        |
| `purpose`                             | Purpose of this contract                                 |
| `human_readable_description`          | Readable description for end users                       |
| `json_parseable_description`          | JSON-compatible description for processing               |
| `contract_parties_roles_mapping`      | Role mapping for parties                                 |

---

### **SubContract Fields**

| Field                                | Description                                         |
| ------------------------------------ | --------------------------------------------------- |
| `sub_contract_id`                    | Unique ID for the sub-contract                      |
| `contract_id`                        | Reference to parent contract                        |
| `sub_contract_clause_data`           | List of clauses inside sub-contract                 |
| `sub_contract_json_repr`             | Full JSON dump for machine processing               |
| `sub_contract_parties_ids`           | Parties involved in the sub-contract                |
| `sub_contract_status`                | Current status of the sub-contract                  |
| `sub_contract_actions_map`           | Mapping of all actions in this sub-contract         |
| `sub_contract_verification_map`      | Mapping of all verifications in this sub-contract   |
| `sub_contract_creation_time`         | When this sub-contract was created                  |
| `last_update_time`                   | When last updated                                   |
| `sub_report_url`                     | Link to sub-contract report if available            |
| `verification_subjects_list`         | Subjects that will perform verification             |
| `purpose`                            | Purpose of this sub-contract                        |
| `json_parseable_description`         | JSON-compatible description for parsing             |
| `sub_clause_constraints`             | List of constraint IDs applied to this sub-contract |
| `sub_contract_parties_roles_mapping` | Roles and parties mapping                           |
| `human_readable_description`         | Human-readable format                               |

---

### **Action Fields**

| Field                                | Description                          |
| ------------------------------------ | ------------------------------------ |
| `action_id`                          | Unique ID for action                 |
| `sub_clause_id`                      | Clause this action is tied to        |
| `action_type`                        | Type of action (e.g. approve, sign)  |
| `action_fulfillment_dsl_workflow_id` | Workflow to fulfill this action      |
| `action_execution_status`            | Status of action execution           |
| `action_execution_config`            | Runtime configuration for the action |
| `action_outcome_data`                | Output of the action if completed    |
| `action_execution_ppt_dsl`           | Optional DSL for UI display          |
| `action_execution_constraint_ids`    | Related constraints for this action  |

---

### **VerificationEntry Fields**

| Field                            | Description                         |
| -------------------------------- | ----------------------------------- |
| `verification_entry_id`          | ID for the verification entry       |
| `sub_clause_action_type`         | Action type being verified          |
| `verifier_subject_id`            | ID of verifier subject              |
| `verifier_subject_type`          | Type (e.g., user, role) of verifier |
| `verification_dsl_workflow_id`   | Verification logic workflow ID      |
| `verification_mode`              | Manual, automatic, etc.             |
| `verification_config`            | Input config for execution          |
| `verification_status`            | Status of verification              |
| `verification_outcome_data`      | Data produced from verification     |
| `verification_outcome_action_id` | Outcome action ID if chained        |
| `verification_timestamp`         | Timestamp of verification event     |
| `verification_cert_data`         | Certificate if any generated        |
| `sub_clause_id`                  | Clause verified by this entry       |

---

### **SubContractConstraint Fields**

| Field                               | Description                              |
| ----------------------------------- | ---------------------------------------- |
| `constraint_id`                     | Unique ID for constraint                 |
| `sub_clause_id`                     | Clause it constrains                     |
| `constraint_type`                   | Main type of constraint                  |
| `constraint_sub_type`               | Further classification of constraint     |
| `constraint_parameters`             | Raw parameter dict for enforcement       |
| `constraint_policy_id`              | ID of referenced policy if any           |
| `constraint_negotiation_parameters` | Params to support negotiation if allowed |
| `group_ids`                         | Restricted to these group IDs            |
| `role_ids`                          | Restricted to these role IDs             |
| `can_negotiate`                     | Boolean toggle to allow negotiation      |

---

## 3. API Documentation

### 3.1 Create Contract

**Endpoint:** `POST /contract`

**Description:** Upload a full contract JSON including all nested components.

**Request Body:**

```json
{
  "contract": { ... },
  "sub_contracts": [ ... ],
  "actions": [ ... ],
  "verification_entries": [ ... ],
  "constraints": [ ... ]
}
```

**Response:**

```json
{
  "success": true,
  "message": "Contract created successfully",
  "result": { ... }
}
```

**cURL Example:**

```bash
curl -X POST http://localhost:5000/contract \
     -H "Content-Type: application/json" \
     -d @full_contract.json
```

---

### 3.2 Update Contract

**Endpoint:** `PUT /contract`

**Description:** Update the contract or any of its sub-documents.

**Request Body:** Same as Create Contract

**Response:**

```json
{
  "success": true,
  "message": "Contract updated successfully",
  "result": { ... }
}
```

**cURL Example:**

```bash
curl -X PUT http://localhost:5000/contract \
     -H "Content-Type: application/json" \
     -d @updated_contract.json
```

---

### 3.3 Delete Full Contract

**Endpoint:** `DELETE /contract/<contract_id>`

**Description:** Deletes the contract and all related subdocuments (cascading delete).

**Response:**

```json
{
  "success": true,
  "message": "Contract and subdocuments deleted",
  "result": { ... }
}
```

**cURL Example:**

```bash
curl -X DELETE http://localhost:5000/contract/contract_abc_123
```

---

### 3.4 Delete Sub-Document

**Endpoint:** `DELETE /contract/subdocument/<doc_type>/<doc_id>`

**Description:** Delete a single sub-document by type and ID.

**doc\_type values:** `sub_contract`, `action`, `verification_entry`, `constraint`

**Response:**

```json
{
  "success": true,
  "message": "<doc_type> deleted",
  "result": 1
}
```

**cURL Example:**

```bash
curl -X DELETE http://localhost:5000/contract/subdocument/action/action_123
```


## Query APIs

### API: Get Full Contract Report

**Endpoint:**
`GET /contract/<contract_id>/report`

**Description:**
Fetches the complete contract specification including all associated sub-documents:

* Contract
* Sub-contracts
* Actions
* Verification Entries
* Constraints

---

#### Path Parameters

| Parameter     | Type   | Required | Description                        |
| ------------- | ------ | -------- | ---------------------------------- |
| `contract_id` | string | Yes    | ID of the contract to be retrieved |

---

#### Response Format

**Success (200 OK):**

```json
{
  "success": true,
  "data": {
    "contract": { ... },
    "sub_contracts": [ ... ],
    "actions": [ ... ],
    "verification_entries": [ ... ],
    "constraints": [ ... ]
  }
}
```

**Not Found (404):**

```json
{
  "success": false,
  "error": "Contract with ID '...' not found."
}
```

**Error (500):**

```json
{
  "success": false,
  "error": "Internal error message"
}
```

---

#### Example cURL Request

```bash
curl -X GET http://localhost:5000/contract/contract_abc123/report
```

---


### **API: Get Contract by ID**

**Endpoint:**
`GET /contract/<contract_id>`

**Success Response (200 OK):**

```json
{
  "success": true,
  "data": {
    "contract_id": "contract-001",
    "contract_type": "service",
    "contract_parties_ids": ["party-123", "party-456"],
    "contract_parent_org_id": "org-789",
    "contract_acl_data": {
      "read": ["party-123"],
      "write": ["party-456"]
    },
    "contract_acl": {
      "effective": ["party-123", "party-456"]
    },
    "contract_sub_clauses_id": ["sub-001", "sub-002"],
    "contract_status": "active",
    "contract_creation_time": "2024-11-01T10:00:00Z",
    "last_update_time": "2025-05-01T15:30:00Z",
    "contract_final_completion_timestamp": null,
    "final_verifier_id": null,
    "report_url": null,
    "purpose": "Legal service agreement",
    "human_readable_description": "This contract outlines service terms between parties.",
    "json_parseable_description": "{\"terms\": [\"service\", \"payment\"]}",
    "contract_parties_roles_mapping": {
      "party-123": "provider",
      "party-456": "client"
    }
  }
}
```

---

### **API: Get Sub-Contract by ID**

**Endpoint:**
`GET /sub_contract/<sub_contract_id>`

**Success Response (200 OK):**

```json
{
  "success": true,
  "data": {
    "sub_contract_id": "sub-001",
    "contract_id": "contract-001",
    "sub_contract_clause_data": [
      {"clause": "Deliver report within 30 days"}
    ],
    "sub_contract_json_repr": {
      "clauses": ["Deliver report within 30 days"]
    },
    "sub_contract_parties_ids": ["party-123", "party-456"],
    "sub_contract_status": "active",
    "sub_contract_actions_map": {
      "notify": "action-001"
    },
    "sub_contract_verification_map": {
      "verified_by": "verifier-001"
    },
    "sub_contract_creation_time": "2024-11-05T12:00:00Z",
    "last_update_time": "2025-05-01T15:30:00Z",
    "sub_report_url": null,
    "verification_subjects_list": ["party-456"],
    "purpose": "Specific service deliverable",
    "json_parseable_description": "{\"clause\": \"Deliver report\"}",
    "sub_clause_constraints": ["constraint-001"],
    "sub_contract_parties_roles_mapping": {
      "party-123": "executor",
      "party-456": "reviewer"
    },
    "human_readable_description": "This sub-contract outlines deliverables."
  }
}
```

---

### **API: Get Action by ID**

**Endpoint:**
`GET /action/<action_id>`

**Success Response (200 OK):**

```json
{
  "success": true,
  "data": {
    "action_id": "action-001",
    "sub_clause_id": "sub-001",
    "action_type": "notify",
    "action_fulfillment_dsl_workflow_id": "workflow-001",
    "action_execution_status": "pending",
    "action_execution_config": {
      "method": "email",
      "recipient": "party-456"
    },
    "action_outcome_data": null,
    "action_execution_ppt_dsl": null,
    "action_execution_constraint_ids": ["constraint-002"]
  }
}
```

---

### **API: Get Sub-Contract Constraint by ID**

**Endpoint:**
`GET /sub_contract_constraint/<constraint_id>`

**Success Response (200 OK):**

```json
{
  "success": true,
  "data": {
    "constraint_id": "constraint-001",
    "sub_clause_id": "sub-001",
    "constraint_type": "time_limit",
    "constraint_sub_type": "absolute",
    "constraint_parameters": {
      "deadline": "2025-06-01T00:00:00Z"
    },
    "constraint_policy_id": null,
    "constraint_negotiation_parameters": null,
    "group_ids": ["group-001"],
    "role_ids": ["reviewer"],
    "can_negotiate": false
  }
}
```

---

### **API: Get Verification Entry by ID**

**Endpoint:**
`GET /verification_entry/<entry_id>`

**Success Response (200 OK):**

```json
{
  "success": true,
  "data": {
    "verification_entry_id": "verify-001",
    "sub_clause_action_type": "notify",
    "verifier_subject_id": "verifier-001",
    "verifier_subject_type": "user",
    "verification_dsl_workflow_id": "workflow-002",
    "verification_mode": "manual",
    "verification_config": {
      "check": "signature"
    },
    "verification_status": "approved",
    "verification_outcome_data": {
      "approved_on": "2025-05-20T10:30:00Z"
    },
    "verification_outcome_action_id": "action-001",
    "verification_timestamp": "2025-05-20T10:30:00Z",
    "verification_cert_data": {
      "signature": "abcdefg12345"
    },
    "sub_clause_id": "sub-001"
  }
}
```

---

## Contracts Verification

### 1. Overview

This document outlines the flow of sub-contract updates, the verification and action execution process, and provides structured documentation for the REST and WebSocket APIs used in the contract management system.

---

### 2. Sub-Contract Update & Verification Flow

The sub-contract update process supports event-driven transitions based on DSL execution. Each event may trigger either:

* A **verification check**, or
* An **action execution**, or
* A fallback to **automatic fulfillment**.

#### 2.1 Process Flow

| Step | Description                                                                                                                                     |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | The system receives an event targeting a specific sub-contract via WebSocket or internal API call.                                              |
| 2    | The sender is validated against the sub-contract's `sub_contract_parties_ids`.                                                                  |
| 3    | If the event type exists in `sub_contract_verification_map`, verification is initiated.                                                         |
| 4    | If not, and the event type exists in `sub_contract_actions_map`, the related action is executed.                                                |
| 5    | If neither verification nor action is mapped, the sub-contract status is marked as `fulfilled` and a message is pushed to all involved parties. |

### 2.2 Verification Logic

| Phase              | Description                                                                       |
| ------------------ | --------------------------------------------------------------------------------- |
| Fetch Verification | Loads the verification entry from DB using `verification_id`.                     |
| Execute DSL        | A workflow is executed via `new_dsl_workflow_executor`.                           |
| Result             | The result is parsed using `parse_dsl_output`.                                    |
| Optional Action    | If `verification_outcome_action_id` is present, corresponding action is executed. |
| Final Step         | If no action is linked, the sub-contract is marked as fulfilled.                  |

### 2.3 Action Execution Logic

| Phase               | Description                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------- |
| Fetch Action        | Loads the action from DB.                                                                |
| Evaluate PQT        | Executes `action_execution_ppt_dsl` using `eval` in a restricted environment.            |
| Execute Fulfillment | If PQT passes, the main workflow is executed using `action_fulfillment_dsl_workflow_id`. |

---

### 3. REST API: Trigger Verification

#### Endpoint

`POST /verification/<verification_id>`

### Description

Executes a verification step using the provided `verification_id` and associated DSL logic.

#### Request Body

```json
{
  "sender_subject_id": "string",
  "event_data": { ... },
  "sub_contract_document": { ... }
}
```

#### Required Fields

| Field                   | Type   | Description                                                               |
| ----------------------- | ------ | ------------------------------------------------------------------------- |
| `sender_subject_id`     | string | The subject initiating the verification. Must match a sub-contract party. |
| `event_data`            | object | Input payload for the DSL execution.                                      |
| `sub_contract_document` | object | Full sub-contract document as fetched from the DB.                        |

#### Response

```json
{
  "success": true,
  "data": {
    "verified": true,
    "data": { ... }
  }
}
```

If the verification fails or errors occur:

```json
{
  "success": false,
  "message": "Error message"
}
```

---

### 4. WebSocket Server: Sub-Contract Event Interface

#### Description

The WebSocket server provides a real-time event-driven interface to trigger sub-contract updates and verification/action workflows.

#### Connection

* URL: `ws://<host>:6789`

#### Workflow

| Step | Description                                                                           |
| ---- | ------------------------------------------------------------------------------------- |
| 1    | A client connects via WebSocket and sends a JSON payload.                             |
| 2    | The message is parsed and validated for required fields.                              |
| 3    | The task is queued for asynchronous execution.                                        |
| 4    | A background processor invokes `invoke_sub_contract_update` and waits for completion. |
| 5    | The result is sent back to the client and the connection is closed.                   |

#### Payload Format

```json
{
  "sub_contract_id": "string",
  "event_type": "string",
  "event_data": { ... },
  "sender_subject_id": "string"
}
```

#### Required Fields

| Field               | Type   | Description                                                            |
| ------------------- | ------ | ---------------------------------------------------------------------- |
| `sub_contract_id`   | string | Unique ID of the sub-contract to be updated.                           |
| `event_type`        | string | Event label that maps to either verification or action.                |
| `event_data`        | object | Payload passed to DSL workflows.                                       |
| `sender_subject_id` | string | Initiator of the event. Must be listed as a party in the sub-contract. |

#### Response Format

```json
{
  "success": true,
  "message": "...",
  "event_data": { ... }
}
```

#### Error Example

```json
{
  "success": false,
  "message": "Missing required fields"
}
```

---

