\# Robot Evaluation Platform — Contract v1.0



\*\*Status:\*\* Frozen  

\*\*Version:\*\* v1.0.0  

\*\*Last updated:\*\* 2026-02-01  

\*\*Applies to:\*\* Backend API, Workers, UI  

\*\*Scope:\*\* Robotics \& Safety-Critical Evaluation (Simulation + Real Systems)



This document defines the \*\*stable behavioral and API contract\*\* for version v1 of the Robot Evaluation Platform.



All production behavior, API semantics, and UI assumptions must conform to this contract.

Any breaking change requires a new contract version (v2).



---



\## Contents

1\. Purpose \& Guarantees  

2\. Core Domain Objects  

3\. State Machines \& Invariants  

4\. Release Decision Semantics  

5\. API Contract (v1)  

6\. Error Handling Contract  

7\. UI Guarantees  

8\. Backward Compatibility Rules  

9\. Safety-Critical / Medical Framing  



---



\## 1. Purpose \& Guarantees



The Robot Evaluation Platform provides \*\*automated regression evaluation and release gating\*\*

for robotics and safety-critical systems.



\### The platform guarantees:

\- Deterministic \*\*PASS / FAIL\*\* gate evaluation

\- Reproducible comparison against a locked baseline

\- A single authoritative \*\*SHIP / BLOCK / PENDING\*\* release decision

\- Traceability across runs, gates, and releases

\- Conservative behavior in the presence of missing or invalid data



---



\## 2. Core Domain Objects



\### 2.1 Run



A \*\*Run\*\* represents one execution of a model on a given suite and dataset using a backend

(e.g. MuJoCo, Gazebo, real robot).



\#### Run Fields (v1 minimum)

\- `id` (integer, unique)

\- `status` (enum: `queued | running | completed | failed`)

\- `created\_at` (ISO-8601 timestamp)

\- `started\_at` (ISO-8601 timestamp | null)

\- `ended\_at` (ISO-8601 timestamp | null)



\- `backend` (string, e.g. `"mujoco"`)

\- `model\_name` (string)

\- `suite\_name` (string)

\- `dataset\_name` (string)



\- `summary\_json` (JSON | null) — aggregated metrics

\- `report\_uri` (string | null) — HTML report

\- `rollout\_uri` (string | null) — video / trajectory artifact



\#### Run Invariants

\- `started\_at` MUST be set once status transitions from `queued`

\- `ended\_at` MUST be set iff status ∈ `{completed, failed}`

\- Only `completed` runs are eligible for gate evaluation



---



\### 2.2 Gate Evaluation



A \*\*Gate Evaluation\*\* compares a \*\*candidate run\*\* against a \*\*baseline run\*\*

and produces a regression verdict.



\#### Gate Fields (v1 minimum)

\- `id` (integer, unique)

\- `baseline\_run\_id` (integer)

\- `candidate\_run\_id` (integer)

\- `status` (enum: `pass | fail | pending | error`)

\- `details\_json` (JSON | null)

\- `created\_at` (ISO-8601 timestamp)



\#### Gate Invariants

\- Gate evaluation MUST compare exactly one baseline and one candidate

\- A `pass` or `fail` result MUST be derived from completed runs

\- Gate evaluation MUST be idempotent for the same baseline/candidate pair

\- `error` is treated as a conservative failure at release level



---



\### 2.3 Baseline Lock



A \*\*Baseline Lock\*\* defines the officially approved reference run

for a suite + dataset + backend.



\#### BaselineLock Fields (v1 minimum)

\- `id` (integer, unique)

\- `suite\_id` (integer)

\- `dataset\_id` (integer)

\- `backend` (string)

\- `baseline\_run\_id` (integer)

\- `created\_at` (ISO-8601 timestamp)



\#### BaselineLock Invariants

\- At most \*\*one active baseline\*\* exists per `(suite\_id, dataset\_id, backend)`

\- The \*\*latest baseline lock\*\* is authoritative

\- Baseline changes do NOT retroactively modify past gate results



---



\## 3. State Machines \& Invariants



\### Run lifecycle

queued → running → completed

↘ failed



\### Gate lifecycle

pending → pass

→ fail

→ error





\### Release lifecycle





PENDING → SHIP

→ BLOCK





---



\## 4. Release Decision Semantics



A \*\*Release Decision\*\* summarizes whether the system is safe to deploy.



\### Decision Enum

\- `SHIP` — safe to deploy

\- `BLOCK` — deployment blocked

\- `PENDING` — insufficient information



\### Decision Rules (v1)

For a given `(suite\_id, dataset\_id, backend)`:



1\. If \*\*no baseline lock exists\*\* → `PENDING`

2\. Else select the \*\*latest completed candidate run\*\*

3\. If no candidate run exists → `PENDING`

4\. If no gate evaluation exists → `PENDING`

5\. If latest gate status = `pass` → `SHIP`

6\. If latest gate status ∈ `{fail, error}` → `BLOCK`



> The system MUST prefer false negatives over false positives.



---



\## 5. API Contract (v1 Namespace)



All v1 endpoints MUST be exposed under:







/api/v1





\### 5.1 Runs

\- `GET /api/v1/runs`

\- `GET /api/v1/runs/{id}`

\- `POST /api/v1/runs/{id}/enqueue`



\### 5.2 Gates

\- `POST /api/v1/gates/evaluate`

&nbsp; ```json

&nbsp; {

&nbsp;   "suite\_id": 1,

&nbsp;   "dataset\_id": 1,

&nbsp;   "backend": "mujoco",

&nbsp;   "candidate\_run\_id": 51

&nbsp; }





GET /api/v1/gates



GET /api/v1/gates/{id}



5.3 Baselines



POST /api/v1/baselines/lock



{

&nbsp; "suite\_id": 1,

&nbsp; "dataset\_id": 1,

&nbsp; "backend": "mujoco",

&nbsp; "baseline\_run\_id": 41

}





GET /api/v1/baselines/latest



5.4 Releases



GET /api/v1/releases/latest



Response:



{

&nbsp; "decision": "SHIP",

&nbsp; "baseline\_run\_id": 41,

&nbsp; "candidate\_run\_id": 51,

&nbsp; "gate\_id": 7,

&nbsp; "updated\_at": "2026-01-31T21:46:00Z",

&nbsp; "why": "Candidate passed all regression checks"

}



6\. Error Handling Contract



All errors MUST follow this structure:



{

&nbsp; "error\_code": "BASELINE\_NOT\_FOUND",

&nbsp; "message": "No baseline lock exists for this suite/dataset/backend",

&nbsp; "hint": "Create a baseline lock using POST /api/v1/baselines/lock"

}





Errors MUST be deterministic and human-readable.



7\. UI Guarantees



The UI is allowed to assume:



Each run has at most one relevant gate vs the active baseline



Gate badges reflect latest gate status



Overview page reflects /api/v1/releases/latest



SHIP implies safe deployment



BLOCK implies regression or error



PENDING implies missing data



8\. Backward Compatibility Rules



v1 API behavior MUST NOT change after release



New fields may be added but MUST be optional



New endpoints MUST NOT alter existing semantics



Breaking changes require a v2 contract



9\. Safety-Critical \& Medical Framing



This platform is suitable for safety-critical and medical evaluation workflows.



Concept Mapping

Platform Concept	Safety / Medical Meaning

Run	Test execution

Gate	Acceptance criterion

Baseline	Approved reference

SHIP	Release

BLOCK	Do not release



The platform is evaluation-only and does not perform clinical decisions.



End of Contract v1.0





---



\## ✅ What to do now (very important)



1\. Paste this into `docs/CONTRACT\_V1.md`

2\. Save the file

3\. Commit it:



```powershell

git add docs\\CONTRACT\_V1.md

git commit -m "docs: freeze v1 contract for runs, gates, and releases"

