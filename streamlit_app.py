
import json
import time
import uuid
import re
from typing import Dict, Any, List

import boto3
from botocore.config import Config
import streamlit as st


def _client(region: str, timeout: int) -> Any:
    cfg = Config(
        connect_timeout=10,
        read_timeout=timeout,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    return boto3.client("bedrock-agentcore", region_name=region, config=cfg)


def _invoke(arn: str, client, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode("utf-8"),
    )
    return _parse_json(_read_body(resp))


def _read_body(resp: Dict[str, Any]) -> str:
    content_type = resp.get("contentType", "")
    if "text/event-stream" in content_type:
        body: List[str] = []
        for raw in resp["response"].iter_lines(chunk_size=1):
            if raw:
                body.append(raw.decode("utf-8"))
        return "\n".join(body)
    body_obj = resp.get("response")
    if hasattr(body_obj, "read"):
        return body_obj.read().decode("utf-8")
    return str(body_obj)


def _parse_json(body: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(body)
        if isinstance(parsed, str):
            return json.loads(parsed)
        return parsed
    except Exception:
        return {"_raw": body}


def launch_job(client, arn: str, region: str, timeout: int, user_inputs: Dict[str, str]) -> Dict[str, Any]:
    payload = {
        "action": "start",
        "userId": user_inputs["user_id"],
        "requestId": user_inputs["request_id"],
        "prompt": user_inputs["prompt"] or (
            f"Plan a trip to {user_inputs['destination']} from {user_inputs['start']} "
            f"to {user_inputs['end']}. Preferences: {user_inputs['preferences']}"
        ),
        "destination": user_inputs["destination"],
        "startDate": user_inputs["start"],
        "endDate": user_inputs["end"],
        "preferences": user_inputs["preferences"],
    }
    return _invoke(arn, client, payload)


def poll_status(client, arn: str, user_id: str, request_id: str) -> Dict[str, Any]:
    payload = {"action": "status", "userId": user_id, "requestId": request_id}
    return _invoke(arn, client, payload)


TRACE_PATTERN = re.compile(r"^(STATUS|TOOL|TOOL_RESULT|RESULT):.*", re.MULTILINE)


def extract_trace(final_text: str) -> List[str]:
    if not final_text:
        return []
    matches = TRACE_PATTERN.findall(final_text)
    if matches:
        return [m.group(0) for m in TRACE_PATTERN.finditer(final_text)]
    
    lines = []
    for line in final_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("STATUS:", "TOOL:", "TOOL_RESULT:", "RESULT:")):
            lines.append(stripped)
    return lines


def main() -> None:
    st.set_page_config(page_title="AgentCore Travel Planner", layout="wide")
    st.title("AgentCore Travel Planner")

    with st.sidebar:
        st.header("Runtime Settings")
        arn = st.text_input("Agent Runtime ARN", key="arn", placeholder="arn:aws:bedrock-agentcore:...")
        region = st.text_input("AWS Region", value="us-east-1")
        timeout = st.number_input("Client Timeout (seconds)", min_value=30, max_value=600, value=120, step=10)
        poll_interval = st.number_input("Poll Interval (seconds)", min_value=2, max_value=30, value=4, step=1)

    with st.form("trip_form"):
        st.subheader("Trip Details")
        user_id = st.text_input("User ID", value=f"u-{uuid.uuid4()}").strip()
        destination = st.text_input("Destination (City, Country)")
        start_date = st.text_input("Start Date (YYYY-MM-DD)")
        end_date = st.text_input("End Date (YYYY-MM-DD)")
        preferences = st.text_input("Preferences (comma-separated)")
        prompt = st.text_area("Additional Prompt (optional)", height=100)
        submitted = st.form_submit_button("Plan Trip")

    if submitted:
        if not arn:
            st.error("Agent Runtime ARN is required.")
            return
        if not destination or not start_date or not end_date:
            st.error("Destination, start date, and end date are required.")
            return

        client = _client(region, timeout)
        user_inputs = {
            "user_id": user_id or f"u-{uuid.uuid4()}",
            "request_id": str(uuid.uuid4()),
            "destination": destination,
            "start": start_date,
            "end": end_date,
            "preferences": preferences,
            "prompt": prompt,
        }

        with st.spinner("Submitting job to AgentCore…"):
            ack = launch_job(client, arn, region, timeout, user_inputs)

        st.write("### Job Acknowledgement")
        st.json(ack)

        result = ack.get("result")
        job_user = ack.get("userId", user_inputs["user_id"])
        job_request = ack.get("requestId", user_inputs["request_id"])

        if result != "accepted":
            st.error("Job was not accepted by the runtime. See acknowledgement payload above for details.")
            return

        progress_area = st.empty()
        status_area = st.empty()
        final_area = st.empty()

        seen = 0
        try:
            while True:
                data = poll_status(client, arn, job_user, job_request)
                job = data.get("job", {})
                progress = job.get("progress", [])
                status = job.get("status", "?")
                new_lines = progress[seen:]
                if new_lines:
                    seen = len(progress)
                    progress_area.markdown(
                        "\n".join(f"- {line}" for line in progress),
                        help="Live progress as reported by the agent.",
                    )
                status_area.info(f"Status: {status}")

                if status in ("SUCCEEDED", "FAILED"):
                    final_msg = job.get("finalMessage") or data.get("message") or "No final message."
                    if status == "SUCCEEDED":
                        final_area.success("Job completed successfully.")
                    else:
                        final_area.error("Job failed.")
                    final_area.markdown(f"#### Final Message\n\n{final_msg}")

                    trace_lines = extract_trace(final_msg)
                    if trace_lines:
                        st.markdown("#### Thinking Trace")
                        st.markdown("\n".join(f"- {line}" for line in trace_lines))

                    iid = job.get("resultItineraryId")
                    if iid:
                        st.info(f"Itinerary ID: {iid}")
                    break

                time.sleep(poll_interval)
        except Exception as exc:
            st.error(f"Error while polling job status: {exc}")


if __name__ == "__main__":
    main()
