import os
from dotenv import load_dotenv

load_dotenv()

TFY_API_TOKEN = os.environ["TFY_API_TOKEN"]
GATEWAY_BASE_URL = os.environ["GATEWAY_BASE_URL"].rstrip("/")
MODEL = os.environ.get("TFY_MODEL", "openai/gpt-4o")
MCP_SERVER_URL = os.environ.get(
    "FAILSAFE_MCP_SERVER_URL",
    "https://gateway.truefoundry.ai/iiitbhagalpur/mcp/failsafe-foundry/server",
)