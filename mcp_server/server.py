from fastmcp import FastMCP
from pathlib import Path
import subprocess
import os

ALLOWED_PATCH_PREFIXES = [
    "app/routes/",
    "app/models.py",
    "tests/",
    "CHANGELOG.md",
    "README.md",
]

BLOCKED_PATCH_PREFIXES = [
    ".github/",
    "infra/",
    "deploy/",
    ".env",
    ".env.",
    "secrets/",
]

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/app/target")).resolve()
port = int(os.environ.get("PORT", "8000"))

mcp = FastMCP("failsafe-validation-tools")


@mcp.tool
def ping() -> dict:
    """Health check."""
    return {
        "status": "ok",
        "project_root": str(PROJECT_ROOT)
    }


@mcp.tool
def list_project_files() -> list[str]:
    """List top-level files in the target project."""
    if not PROJECT_ROOT.exists():
        return [f"PROJECT_ROOT not found: {PROJECT_ROOT}"]
    return sorted([p.name for p in PROJECT_ROOT.iterdir()])


@mcp.tool
def run_tests() -> dict:
    """Run pytest in the target project."""
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

@mcp.tool
def validate_patch_scope(files: list[str]) -> dict:
    """Validate whether a proposed patch only touches approved files."""
    allowed = []
    blocked = []
    unknown = []

    for file_path in files:
        normalized = file_path.strip().lstrip("./")

        if any(
            normalized == blocked_prefix or normalized.startswith(blocked_prefix)
            for blocked_prefix in BLOCKED_PATCH_PREFIXES
        ):
            blocked.append(normalized)
            continue

        if any(
            normalized == allowed_prefix or normalized.startswith(allowed_prefix)
            for allowed_prefix in ALLOWED_PATCH_PREFIXES
        ):
            allowed.append(normalized)
        else:
            unknown.append(normalized)

    ok = len(blocked) == 0 and len(unknown) == 0

    return {
        "ok": ok,
        "allowed_files": allowed,
        "blocked_files": blocked,
        "unknown_files": unknown,
        "allowed_prefixes": ALLOWED_PATCH_PREFIXES,
        "blocked_prefixes": BLOCKED_PATCH_PREFIXES,
        "message": (
            "Patch scope approved"
            if ok
            else "Patch scope rejected because some files are blocked or outside the approved scope"
        ),
    }

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)