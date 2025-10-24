# invoke.py
import argparse
import json
import sys
import uuid

import boto3
from botocore.config import Config


def print_json_stream_or_body(resp):
    content_type = resp.get("contentType", "")
    if "text/event-stream" in content_type:
        print("=== Streaming ===")
        for raw in resp["response"].iter_lines(chunk_size=1):
            if not raw:
                continue
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = str(raw)
            if text.startswith("data: "):
                text = text[6:]
            print(text)
            sys.stdout.flush()
    else:
        body = resp.get("response")
        print(body.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Invoke AgentCore runtime (interactive).")
    parser.add_argument("--arn", required=True, help="Agent Runtime ARN")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    user_id = input("userId: ").strip() or f"u-{uuid.uuid4()}"
    destination = input("destination (City, Country): ").strip()
    start_date = input("startDate (YYYY-MM-DD): ").strip()
    end_date = input("endDate (YYYY-MM-DD): ").strip()
    preferences = input("preferences (comma-separated): ").strip()
    prompt = input("prompt (free text, optional): ").strip()

    cfg = Config(
        connect_timeout=10,
        read_timeout=args.timeout,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    client = boto3.client("bedrock-agentcore", region_name=args.region, config=cfg)

    payload = {
        "userId": user_id,
        "requestId": str(uuid.uuid4()),
        "prompt": prompt or f"Plan a trip to {destination} from {start_date} to {end_date}. Preferences: {preferences}",
        "destination": destination,
        "startDate": start_date,
        "endDate": end_date,
        "preferences": preferences,
    }

    resp = client.invoke_agent_runtime(
        agentRuntimeArn=args.arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode("utf-8"),
    )
    print_json_stream_or_body(resp)


if __name__ == "__main__":
    main()
