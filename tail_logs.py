
import argparse
import time

import boto3


def tail(log_group, region, start_ms=None, pattern=None):
    logs = boto3.client("logs", region_name=region)
    next_token = None
    start_time = start_ms or int(time.time() - 60) * 1000

    while True:
        kwargs = dict(logGroupName=log_group, startTime=start_time, interleaved=True)
        if pattern:
            kwargs["filterPattern"] = pattern
        if next_token:
            kwargs["nextToken"] = next_token

        resp = logs.filter_log_events(**kwargs)
        for event in resp.get("events", []):
            ts = event["timestamp"]
            msg = event["message"].rstrip()
            print(msg)
            if ts + 1 > start_time:
                start_time = ts + 1

        next_token = resp.get("nextToken")
        time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="Tail CloudWatch logs for an AgentCore runtime.")
    parser.add_argument("--log-group", required=True, help="Log group name (/aws/bedrock/agentcore/runtimes/<runtime-id>)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--since-seconds", type=int, default=120)
    parser.add_argument("--filter", help="Filter pattern (e.g., requestId or sessionId)")
    args = parser.parse_args()

    start_ms = int((time.time() - args.since_seconds) * 1000)
    tail(args.log_group, args.region, start_ms, args.filter)


if __name__ == "__main__":
    main()
