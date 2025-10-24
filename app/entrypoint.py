import uuid
import traceback
from typing import Dict, Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .agent_builder import build_agent, discover_gateway_tools
from .config import log, AWS_REGION, DDB_REGION

app = BedrockAgentCoreApp()
_baseline_agent = build_agent()

log.setLevel("DEBUG")


def _agent_for_request():
    extra_tools = discover_gateway_tools()
    if not extra_tools:
        log.debug("[invoke] using baseline agent (no gateway tools available)")
        return _baseline_agent
    log.debug(f"[invoke] rebuilding agent with {len(extra_tools)} gateway tool(s)")
    try:
        return build_agent(extra_tools=extra_tools)
    except Exception:
        log.exception("[gateway] failed to build agent with extra tools; falling back to baseline")
        return _baseline_agent


@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload keys: userId, requestId, prompt, destination, startDate, endDate, preferences
    """
    user_id = payload.get("userId", f"u-{uuid.uuid4()}")
    request_id = payload.get("requestId", str(uuid.uuid4()))
    destination = payload.get("destination", "")
    start_date = payload.get("startDate", "")
    end_date = payload.get("endDate", "")
    prefs = payload.get("preferences", "")
    nl_query = payload.get("prompt") or f"Plan a trip to {destination} from {start_date} to {end_date}. Preferences: {prefs}"

    log.info(f"[invoke] userId={user_id} requestId={request_id} region={AWS_REGION} ddb_region={DDB_REGION}")
    log.info(f"[invoke] nl_query={nl_query}")
    log.debug(f"[invoke] destination={destination} start={start_date} end={end_date} prefs={prefs}")

    context = (
        f"UserId: {user_id}\n"
        f"RequestId: {request_id}\n"
        f"Destination: {destination}\n"
        f"Dates: {start_date} to {end_date}\n"
        f"Preferences: {prefs}\n\n"
        "Follow the protocol; emit STATUS/TOOL lines; call save_itinerary exactly once."
    )

    agent = _agent_for_request()

    try:
        result = agent(f"{context}\n\nUser request: {nl_query}")
        return {
            "result": "ok",
            "userId": user_id,
            "requestId": request_id,
            "message": "" if result is None else str(result),
        }
    except Exception as exc:
        log.error("[invoke] error", exc_info=True)
        return {
            "result": "error",
            "error": str(exc),
            "trace": traceback.format_exc()[:3800],
            "userId": user_id,
            "requestId": request_id,
        }


if __name__ == "__main__":
    app.run()
