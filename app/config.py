import os
import logging
import uuid
import datetime
import time

import boto3
import requests

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "DEBUG"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("agentcore-poc")

AWS_REGION = os.getenv("AWS_REGION") or boto3.session.Session().region_name or "us-east-1"
DDB_REGION = os.getenv("DDB_REGION", AWS_REGION)
TABLE_NAME = os.getenv("TABLE_NAME", "travel_itineraries")
MODEL_ID   = os.getenv("MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")

GATEWAY_URL = os.getenv("GATEWAY_URL", "https://travel-agent-gateway-ugbk5bivzz.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp")
GATEWAY_ACCESS_TOKEN = os.getenv("GATEWAY_ACCESS_TOKEN", "")
COGNITO_TOKEN_URL = os.getenv("COGNITO_TOKEN_URL", "https://my-domain-grsxuvl5.auth.us-east-1.amazoncognito.com/oauth2/token")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "25asgubgeoi71fqoflug78q2fm")
COGNITO_CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET", "paedup9dujb1viei493o1n4m7v0fnu6jtqu9qqc2sa0j2q60og3")
COGNITO_SCOPE = os.getenv("COGNITO_SCOPE", "")

HTTP_MAX_CALLS = int(os.getenv("HTTP_MAX_CALLS", "8"))

dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table = dynamodb.Table(TABLE_NAME)

def iso_now() -> str:
    return datetime.datetime.utcnow().isoformat()

def new_uuid() -> str:
    return str(uuid.uuid4())

_token_cache = {"access_token": None, "exp": 0}

def _mint_cognito_token() -> str:
    if not (COGNITO_TOKEN_URL and COGNITO_CLIENT_ID and COGNITO_CLIENT_SECRET):
        return ""
    auth = (COGNITO_CLIENT_ID, COGNITO_CLIENT_SECRET)
    data = {"grant_type": "client_credentials", "scope": COGNITO_SCOPE or ""}
    try:
        resp = requests.post(COGNITO_TOKEN_URL, data=data, auth=auth, timeout=10)
        resp.raise_for_status()
    except Exception:
        log.warning("[gateway] failed to mint token via Cognito", exc_info=True)
        return ""
    payload = resp.json()
    _token_cache["access_token"] = payload.get("access_token")
    _token_cache["exp"] = int(time.time()) + int(payload.get("expires_in", 300)) - 30
    return _token_cache["access_token"] or ""

def get_gateway_access_token() -> str:
    if GATEWAY_ACCESS_TOKEN:
        return GATEWAY_ACCESS_TOKEN
    now = int(time.time())
    if _token_cache["access_token"] and now < _token_cache["exp"]:
        return _token_cache["access_token"]
    return _mint_cognito_token()
