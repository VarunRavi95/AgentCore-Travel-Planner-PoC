from typing import Dict, Any, List
import uuid

from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

from strands import tool
from .config import table, iso_now, log


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
    base = request_id or f"{user_id}|{destination}|{start}|{end}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agentcore-poc:{base}"))


@tool
def save_itinerary(userId: str, itinerary: Dict[str, Any], requestId: str = "") -> str:
    """
    Idempotent save. Returns 'saved:<id>' or 'duplicate:<id>'.
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
    it["createdAt"] = iso_now()

    log.info(f"[tool] save_itinerary(userId={userId}, itineraryId={it['itineraryId']})")
    try:
        table.put_item(
            Item=it,
            ConditionExpression="attribute_not_exists(itineraryId)"
        )
        log.info(f"[tool] save_itinerary -> saved:{it['itineraryId']}")
        return f"saved:{it['itineraryId']}"
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            log.info(f"[tool] save_itinerary -> duplicate:{it['itineraryId']}")
            return f"duplicate:{it['itineraryId']}"
        log.exception("[tool] save_itinerary error")
        raise


@tool
def get_itineraries(userId: str, limit: int = 10) -> List[Dict[str, Any]]:
    log.info(f"[tool] get_itineraries(userId={userId}, limit={limit})")
    resp = table.query(
        KeyConditionExpression=Key("userId").eq(userId),
        Limit=limit,
        ScanIndexForward=False
    )
    items = resp.get("Items", [])
    log.info(f"[tool] get_itineraries -> {len(items)} item(s)")
    return items
