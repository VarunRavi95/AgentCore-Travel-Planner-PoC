# app.py
import os
import json
import uuid
import datetime
import logging
import traceback
from typing import Dict, Any, List

import boto3
from botocore.exceptions import ClientError

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel
from strands_tools import http_request  # Strands built-in web fetch tool

# ----------------- logging -----------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("travel-agent")

# ----------------- config -----------------
AWS_REGION = os.getenv("AWS_REGION") or boto3.session.Session().region_name or "us-east-1"
DDB_REGION = os.getenv("DDB_REGION", AWS_REGION)
TABLE_NAME = os.getenv("TABLE_NAME", "travel_itineraries")
MODEL_ID = os.getenv("MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")

dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table = dynamodb.Table(TABLE_NAME)

# AgentCore runtime app
app = BedrockAgentCoreApp()

# ----------------- helpers -----------------
def _iso_now() -> str:
    return datetime.datetime.utcnow().isoformat()

def _ensure_itinerary_shape(itinerary: Dict[str, Any]) -> Dict[str, Any]:
    it = dict(itinerary or {})
    it.setdefault("itineraryId", str(uuid.uuid4()))
    it.setdefault("destination", "")
    it.setdefault("startDate", "")
    it.setdefault("endDate", "")
    it.setdefault("items", [])
    it.setdefault("sources", [])
    return it

def _stable_itinerary_id(user_id: str, destination: str, start: str, end: str, request_id: str = "") -> str:
    """
    Deterministic ID for idempotency. Prefer client-provided requestId; otherwise hash the trip tuple.
    """
    if request_id:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agentcore-poc:{user_id}:{request_id}"))
    raw = f"{user_id}|{destination}|{start}|{end}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

# ----------------- tools -----------------
@tool
def save_itinerary(userId: str, itinerary: Dict[str, Any], requestId: str = "") -> str:
    """
    Idempotent save to DynamoDB. Will NOT overwrite an existing itineraryId.
    Returns: 'saved:<id>' or 'duplicate:<id>'
    """
    it = _ensure_itinerary_shape(itinerary)
    it["userId"] = userId
    it["itineraryId"] = it.get("itineraryId") or _stable_itinerary_id(
        user_id=userId,
        destination=it.get("destination", ""),
        start=it.get("startDate", ""),
        end=it.get("endDate", ""),
        request_id=requestId,
    )
    it["createdAt"] = _iso_now()

    log.info(f"[tool] save_itinerary(userId={userId}, itineraryId={it['itineraryId']})")
    try:
        table.put_item(
            Item=it,
            ConditionExpression="attribute_not_exists(itineraryId)"  # idempotent write
        )
        log.info(f"[tool] save_itinerary -> saved:{it['itineraryId']}")
        return f"saved:{it['itineraryId']}"
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            log.info(f"[tool] save_itinerary -> duplicate:{it['itineraryId']}")
            return f"duplicate:{it['itineraryId']}"
        log.error(f"[tool] save_itinerary error: {e}", exc_info=True)
        raise

@tool
def get_itineraries(userId: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch recent itineraries for a user.
    """
    log.info(f"[tool] get_itineraries(userId={userId}, limit={limit})")
    from boto3.dynamodb.conditions import Key
    resp = table.query(
        KeyConditionExpression=Key("userId").eq(userId),
        Limit=limit,
        ScanIndexForward=False
    )
    items = resp.get("Items", [])
    log.info(f"[tool] get_itineraries -> {len(items)} item(s)")
    return items

# ----------------- model & agent -----------------
# Stream friendly prompt: ask for short STATUS messages (no chain-of-thought) + strict tool limits.
SYSTEM_PROMPT = f"""
You are a travel-planning agent.

Web use policy:
- Use the `http_request` tool at most 8 times in total.
- Prefer official tourism, transport, and Wikipedia pages.
- Stop browsing once you have enough facts.

Interaction protocol (important):
- Emit brief STATUS updates to the user as you proceed (e.g., "STATUS: researching buses", "STATUS: drafting day plan").
  Do NOT reveal internal reasoning; only short progress updates.

Output requirements:
1) Research with `http_request` as needed (<=8 calls).
2) Produce a valid JSON itinerary with fields:
   itineraryId, destination, startDate, endDate, items[], sources[]  (generate itineraryId if missing).
3) Call save_itinerary(userId=<provided_user_id>, itinerary=<json>, requestId=<provided_request_id>) exactly once.

Quality:
- 2–6 activities per day; include travel mode/time and rough cost if available.
- Include source URLs in "sources".
"""

model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    max_tokens=2000,
    temperature=0.3,
    streaming=True,
    include_tool_result_status=True
)

agent = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[http_request, save_itinerary, get_itineraries],
    model=model
)

# ----------------- AgentCore entrypoint -----------------
@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expected payload:
    {
      "userId": "varun-001",
      "requestId": "<uuid>",              # optional but recommended for idempotency
      "prompt": "3-day Kyoto trip ...",
      "destination": "Kyoto, Japan",
      "startDate": "2025-12-14",
      "endDate": "2025-12-16",
      "preferences": "temples, coffee, minimal walking"
    }
    """
    user_id = payload.get("userId", f"u-{uuid.uuid4()}")
    request_id = payload.get("requestId", str(uuid.uuid4()))
    destination = payload.get("destination", "")
    start_date = payload.get("startDate", "")
    end_date = payload.get("endDate", "")
    prefs = payload.get("preferences", "")
    nl_query = payload.get("prompt") or f"Plan a trip to {destination} from {start_date} to {end_date}. Preferences: {prefs}"

    log.info(f"[invoke] userId={user_id} requestId={request_id} region={AWS_REGION} ddb_region={DDB_REGION} table={TABLE_NAME}")
    log.info(f"[invoke] nl_query={nl_query}")

    try:
        planning_context = (
            f"UserId: {user_id}\n"
            f"RequestId: {request_id}\n"
            f"Destination: {destination}\n"
            f"Dates: {start_date} to {end_date}\n"
            f"Preferences: {prefs}\n\n"
            "Follow the protocol precisely; call save_itinerary exactly once."
        )

        # The Strands Agent streams tokens & tool-status; your client will see these live via SSE.
        result = agent(f"{planning_context}\n\nUser request: {nl_query}")

        # Compact response for non-streaming clients
        return {
            "result": "ok",
            "userId": user_id,
            "requestId": request_id,
            "message": str(result)
        }

    except Exception as e:
        log.error("[invoke] error", exc_info=True)
        return {
            "result": "error",
            "error": str(e),
            "trace": traceback.format_exc()[:4000],
            "userId": user_id,
            "requestId": request_id
        }

if __name__ == "__main__":
    app.run()
