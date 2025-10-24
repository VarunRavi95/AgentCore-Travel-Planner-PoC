from typing import List, Optional

from strands import Agent, tool
from strands.models import BedrockModel
from strands_tools import http_request

from .prompts import SYSTEM_PROMPT
from .ddb_tools import save_itinerary, get_itineraries
from .config import MODEL_ID, AWS_REGION, GATEWAY_URL, get_gateway_access_token, log, new_uuid

try:
    from strands.agent.conversation_manager import SlidingWindowConversationManager
except Exception:
    SlidingWindowConversationManager = None
    log.warning("SlidingWindowConversationManager not available; proceeding without conversation truncation.")

try:
    from strands.tools.mcp.mcp_client import MCPClient
    from mcp.client.streamable_http import streamablehttp_client
except Exception:
    MCPClient = None  # type: ignore
    streamablehttp_client = None  # type: ignore
    log.warning("MCP client libraries not available; gateway tools will be skipped.")


def _mcp_client_or_none() -> Optional[MCPClient]:  # type: ignore
    if not (MCPClient and streamablehttp_client):
        log.debug("[gateway] MCP libraries unavailable; cannot create client")
        return None
    if not GATEWAY_URL:
        log.debug("[gateway] GATEWAY_URL unset; skipping gateway tools")
        return None
    log.debug(f"[gateway] preparing MCP client for {GATEWAY_URL}")
    token = get_gateway_access_token()
    if not token:
        log.warning("[gateway] no access token available; proceeding without gateway tools")
        return None
    client = MCPClient(lambda: streamablehttp_client(
        url=GATEWAY_URL,
        headers={"Authorization": f"Bearer {token}"}
    ))
    log.debug("[gateway] MCP client instantiated successfully")
    return client


def _wrap_mcp_tool(tool_name: str, schema: dict | None, description: str | None):
    """
    Create a Strands tool wrapper that proxies calls to the Gateway MCP tool.
    """
    schema = schema or {"type": "object", "properties": {}}
    description = description or f"MCP tool proxy for {tool_name}"

    @tool(name=tool_name, description=description, inputSchema=schema, context="tool_context")
    def _gateway_proxy(*, tool_context: dict, **kwargs):
        client = _mcp_client_or_none()
        if client is None:
            raise RuntimeError("Gateway client unavailable")
        tool_use_id = tool_context.get("tool_use", {}).get("toolUseId") or new_uuid()
        arguments = kwargs or None
        try:
            with client as mcp:
                result = mcp.call_tool_sync(tool_use_id=tool_use_id, name=tool_name, arguments=arguments)
        except Exception as exc:
            log.exception("[gateway] tool %s failed", tool_name)
            raise
        return result

    log.debug(f"[gateway] wrapped MCP tool {tool_name}")
    return _gateway_proxy


def discover_gateway_tools() -> List:
    """
    Return a list of MCP tool descriptors if gateway access is available, else [].
    """
    log.debug("[gateway] attempting to discover available tools")
    client = _mcp_client_or_none()
    if not client:
        log.debug("[gateway] MCP client unavailable; returning no extra tools")
        return []
    try:
        with client as mcp:
            tools = mcp.list_tools_sync()
            log.debug(f"[gateway] list_tools_sync returned {len(tools or [])} record(s)")
    except Exception:
        log.exception("[gateway] failed to list tools")
        return []

    names = []
    for t in tools or []:
        name = getattr(t, "tool_name", None)
        if isinstance(name, str):
            names.append(name)
    if names:
        log.info(f"[gateway] tools discovered: {names}")
    else:
        log.info("[gateway] list_tools_sync returned no named tools")

    wrapped_tools: List = []
    for tool_desc in tools or []:
        try:
            name = getattr(tool_desc, "tool_name", None)
            if not isinstance(name, str):
                continue
            spec = getattr(tool_desc, "tool_spec", {}) or {}
            schema = spec.get("inputSchema") or spec.get("input_schema")
            description = spec.get("description")
            wrapped_tools.append(_wrap_mcp_tool(name, schema, description))
        except Exception:
            log.exception("[gateway] failed to wrap tool %s", getattr(tool_desc, "tool_name", "<unknown>"))
    return wrapped_tools


def build_agent(extra_tools: Optional[List] = None) -> Agent:
    log.debug(f"[agent] building agent with {len(extra_tools or [])} gateway tool(s)")
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=15000,
        temperature=0.2,
    )

    tools = [http_request, save_itinerary, get_itineraries]
    if extra_tools:
        log.debug(f"[agent] appending {len(extra_tools)} gateway tool(s) to baseline set")
        tools.extend(extra_tools)
    else:
        log.debug("[agent] using baseline tool set only")

    kwargs = dict(
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        model=model,
    )

    if SlidingWindowConversationManager is not None:
        kwargs["conversation_manager"] = SlidingWindowConversationManager(
            window_size=18,
            should_truncate_results=True,
        )
        log.debug("[agent] SlidingWindowConversationManager enabled")
    else:
        log.debug("[agent] SlidingWindowConversationManager unavailable; proceeding without it")

    return Agent(**kwargs)
