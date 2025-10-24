from __future__ import annotations
from typing import Dict, Any, Optional
import time
import logging

from botocore.exceptions import ClientError
from .config import table, iso_now, log

JOB_SK_PREFIX = "job#"

def _job_sk(request_id: str) -> str:
    return f"{JOB_SK_PREFIX}{request_id}"

def create_job(user_id: str, request_id: str, meta: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None) -> None:
    """
    Create a job record (idempotent). PK=userId, SK=job#<requestId>.
    """
    item = {
        "userId": user_id,
        "itineraryId": _job_sk(request_id),  
        "type": "job",
        "status": "RUNNING",
        "startedAt": iso_now(),
        "updatedAt": iso_now(),
        "progress": [],
    }
    if meta:
        item["meta"] = meta
    if job_id:
        item["runtimeJobId"] = job_id

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(itineraryId)"
        )
        log.info(f"[job] created userId={user_id} requestId={request_id}")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            log.info(f"[job] already exists userId={user_id} requestId={request_id}")
        else:
            log.exception("[job] create_job error")
            raise

def append_progress(user_id: str, request_id: str, line: str) -> None:
    """
    Append a progress line and update updatedAt. Best-effort (never raises).
    """
    try:
        line = (line or "").strip()
        if not line:
            return
        if len(line) > 600:
            line = line[:600] + " ..."

        table.update_item(
            Key={"userId": user_id, "itineraryId": _job_sk(request_id)},
            UpdateExpression="SET #p = list_append(if_not_exists(#p, :empty), :line), updatedAt = :t",
            ExpressionAttributeNames={"#p": "progress"},
            ExpressionAttributeValues={
                ":empty": [],
                ":line": [f"{time.strftime('%H:%M:%S')}  {line}"],
                ":t": iso_now(),
            },
        )
    except Exception:
        log.exception("[job] append_progress error")

def complete_job(user_id: str, request_id: str, status: str, final_message: Optional[str] = None, itinerary_id: Optional[str] = None) -> None:
    """
    Mark the job as SUCCEEDED/FAILED and store final outputs. Best-effort.
    """
    try:
        expr = ["#s = :s", "completedAt = :t", "updatedAt = :t"]
        names = {"#s": "status"}
        vals = {":s": status, ":t": iso_now()}
        if final_message:
            vals[":m"] = final_message[:180_000]
            expr.append("finalMessage = :m")
        if itinerary_id:
            vals[":iid"] = itinerary_id
            expr.append("resultItineraryId = :iid")

        table.update_item(
            Key={"userId": user_id, "itineraryId": _job_sk(request_id)},
            UpdateExpression="SET " + ", ".join(expr),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
        )
        log.info(f"[job] completed userId={user_id} requestId={request_id} status={status} iid={itinerary_id}")
    except Exception:
        log.exception("[job] complete_job error")

class JobProgressHandler(logging.Handler):
    """
    Optional log-mirror. Attach to root logger during a job to mirror concise lines to DDB.
    """
    def __init__(self, user_id: str, request_id: str, level=logging.INFO):
        super().__init__(level=level)
        self.user_id = user_id
        self.request_id = request_id

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if any(msg.startswith(pfx) for pfx in ("STATUS:", "TOOL:", "TOOL_RESULT:", "Tool #")):
            append_progress(self.user_id, self.request_id, msg)
