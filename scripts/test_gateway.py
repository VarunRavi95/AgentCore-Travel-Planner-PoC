import requests
import json

CLIENT_ID = "25asgubgeoi71fqoflug78q2fm"
CLIENT_SECRET = "paedup9dujb1viei493o1n4m7v0fnu6jtqu9qqc2sa0j2q60og3"
TOKEN_URL = "https://my-domain-grsxuvl5.auth.us-east-1.amazoncognito.com/oauth2/token"

def fetch_access_token(client_id, client_secret, token_url):
  response = requests.post(
    token_url,
    data="grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}".format(client_id=client_id, client_secret=client_secret),
    headers={'Content-Type': 'application/x-www-form-urlencoded'}
  )

  return response.json()['access_token']

def list_tools(gateway_url, access_token):
  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {access_token}"
  }

  payload = {
      "jsonrpc": "2.0",
      "id": "list-tools-request",
      "method": "tools/list"
  }

  response = requests.post(gateway_url, headers=headers, json=payload)
  return response.json()


gateway_url = "https://travel-agent-gateway-ugbk5bivzz.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
access_token = fetch_access_token(CLIENT_ID, CLIENT_SECRET, TOKEN_URL)
tools = list_tools(gateway_url, access_token)
print(json.dumps(tools, indent=2))