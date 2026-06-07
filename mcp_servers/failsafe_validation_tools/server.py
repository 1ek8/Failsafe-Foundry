from fastmcp import FastMCP
from pathlib import Path
import subprocess
import os

mcp = FastMCP("failsafe-validation-tools")

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()

@mcp.tool
def ping() -> dict:
    """Simple health check to verify the MCP server is discoverable."""
    return {
        "status": "ok",
        "project_root": str(PROJECT_ROOT)
    }

@mcp.tool
def list_project_files() -> list[str]:
    """List top-level files in the target project root."""
    if not PROJECT_ROOT.exists():
        return [f"PROJECT_ROOT not found: {PROJECT_ROOT}"]
    return sorted([p.name for p in PROJECT_ROOT.iterdir()])

@mcp.tool
def run_tests() -> dict:
    """Run pytest in the target project and return result."""
    if not PROJECT_ROOT.exists():
        return {"ok": False, "error": f"PROJECT_ROOT not found: {PROJECT_ROOT}"}
    try:
        result = subprocess.run(
            ["pytest", "-q"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:]
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    mcp.run()