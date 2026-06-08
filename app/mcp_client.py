import anyio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from app.config import MCP_SERVER_URL, TFY_API_TOKEN


async def _call_tool_async(tool_name: str, args: dict):
    transport = StreamableHttpTransport(
        url=MCP_SERVER_URL,
        headers={
            "Authorization": f"Bearer {TFY_API_TOKEN}",
        },
    )

    async with Client(transport) as client:
        result = await client.call_tool(tool_name, args)
        return result


def call_mcp_tool(tool_name: str, args: dict):
    return anyio.run(_call_tool_async, tool_name, args)