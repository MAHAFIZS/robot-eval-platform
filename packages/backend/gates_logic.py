import json
from packages.backend.db_exec import fetch_one, exec_returning

def evaluate_gate_for_candidate(*, suite_id: int, dataset_id: int, backend: str, candidate_run_id: int) -> dict:
    # 1) find baseline lock
    lock = fetch_one(
        """
        SELECT baseline_run_id
        FROM baseline_locks
        WHERE suite_id=:suite_id AND dataset_id=:dataset_id AND backend=:backend
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"suite_id": suite_id, "dataset_id": dataset_id, "backend": backend},
    )
    if not lock:
        return {"ok": False, "reason": "no baseline lock"}

    baseline_run_id = lock["baseline_run_id"]

    # 2) load summaries (candidate + baseline)
    base = fetch_one("SELECT summary_json FROM runs WHERE id=:id", {"id": baseline_run_id})
    cand = fetch_one("SELECT summary_json FROM runs WHERE id=:id", {"id": candidate_run_id})

    base_s = base["summary_json"] or {}
    cand_s = cand["summary_json"] or {}

    # 3) your gate rule (example: success_rate must not drop)
    base_sr = base_s.get("success_rate")
    cand_sr = cand_s.get("success_rate")

    status = "pass"
    details = {"baseline_success_rate": base_sr, "candidate_success_rate": cand_sr}

    if base_sr is not None and cand_sr is not None and cand_sr < base_sr:
        status = "fail"
        details["reason"] = "success_rate_regression"

    # 4) insert gate_evaluations row
    row = exec_returning(
        """
        INSERT INTO gate_evaluations (baseline_run_id, candidate_run_id, status, details_json)
        VALUES (:b, :c, :s, CAST(:d AS jsonb))
        RETURNING id, status
        """,
        {"b": baseline_run_id, "c": candidate_run_id, "s": status, "d": json.dumps(details)},
    )

    return {"ok": True, "gate_id": row["id"], "status": row["status"], "baseline_run_id": baseline_run_id}
