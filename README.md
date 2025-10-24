# AgentCore-Travel-Planner-PoC

AgentCore Travel Planner PoC is an end-to-end reference implementation that shows how to orchestrate AWS Bedrock AgentCore runtimes, Strands agents, and third-party travel APIs (OpenTripMap) to build itinerary-planning experiences. It includes:

- **Agent runtime** implemented with Bedrock AgentCore that calls Strands to plan travel, interact with tools (HTTP, DynamoDB, OpenTripMap), and persist itineraries.
- **CLI utilities** to submit jobs.
- **Streamlit front end** for collecting trip requests, monitoring job execution, and reviewing results.
- **Infrastructure scripts** (Dockerfile, AgentCore config) to containerize and deploy the runtime.

> ⚠️ Note: This repository is a proof of concept.

---

## Features

- **Itinerary generation** — AgentCore schedules Strands runs in the background; CLI/UI poll for status.
- **Gateway-integrated tools** — Automatically discovers OpenTripMap MCP tools and wraps them as Strands tools.
- **Persistent storage** — DynamoDB tables store itineraries and job metadata for audit or recall.
- **Observability** — Log-based progress tracing and optional Streamlit trace extraction.
- **Multiple interfaces**:
  - `invoke.py` CLI — quick job submission, status streaming.
  - `streamlit_app.py` — user-friendly front end with configurables.
  - `tail_logs.py` — tail CloudWatch logs via the AWS SDK.

---

## Architecture Overview

```text
┌─────────────┐       ┌────────────────┐        ┌────────────────────┐
│ Streamlit   │──────▶│                │──────▶│ Strands Agent      │
│ or CLI      │       │ Bedrock Agent  │        │  (Claude Sonnet)   │
└─────────────┘       │ Core Runtime   │        └─────────┬──────────┘
                      └────────┬───────┘                  │
                               │                          │ Tool calls
                               │                          ▼
                               │             ┌─────────────────────────────┐
                               │             │ Gateway MCP (OpenTripMap)   │
                               │             └─────────────────────────────┘
                               │
                               │             ┌─────────────────────────────┐
                               └────────────▶│ DynamoDB (Itineraries/Jobs) │
                                             └─────────────────────────────┘
```

---

## Key Components

| Path                      | Description                                                                                  |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| `app/entrypoint.py`       | Bedrock AgentCore entrypoint. Launches background jobs and handles status requests.           |
| `app/agent_builder.py`    | Assembles Strands Agent + tools, wraps OpenTripMap Gateway tools, adds debug logging.        |
| `app/ddb_tools.py`        | Strands tool wrappers for saving & retrieving itineraries from DynamoDB.                     |
| `app/jobs.py`             | Job lifecycle helpers (create/append progress/complete).                                     |
| `app/prompts.py`          | System prompt that enforces HTTP-first, then OpenTripMap tool usage.                         |
| `invoke.py`               | CLI to start/status/follow jobs using boto3.                                                 |
| `streamlit_app.py`        | Streamlit UI for submitting jobs, observing progress, and inspecting traces.                 |
| `tail_logs.py`            | Utility to tail CloudWatch logs (filter on request IDs).                                     |
| `Dockerfile`              | Container definition for the AgentCore runtime (installs requirements, sets environment).    |
| `.bedrock_agentcore.yaml` | AgentCore CLI configuration (entrypoint, runtime, memory, etc.).                             |

---

## Getting Started

### Prerequisites

- Python 3.10+ (CLI/UI)  
- AWS credentials configured via environment, profile, or IAM role  
- `git`, `docker`, and the AWS CLI / AgentCore CLI installed if you plan to rebuild the runtime  
- Optional: Gateway credentials (Cognito client_id/secret + token URL, or pre-minted token)

---

## Roadmap Ideas

- Enrich observability (structured traces, failure alerts).
- Add lodging/flight APIs and multi-agent collaboration.
- Support human-in-the-loop approvals before saving itineraries.
- Improve front-end (editable plans, session history).
