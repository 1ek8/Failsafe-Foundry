from fastmcp import FastMCP
from pathlib import Path
import subprocess
import os
import shutil
import tempfile
import zipfile
import io
import urllib.request
import sys

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
target_repo_url = os.environ.get("TARGET_REPO_URL", "").strip()
target_repo_branch = os.environ.get("TARGET_REPO_BRANCH", "main").strip()
project_root = Path(os.environ.get("PROJECT_ROOT", "/tmp/apicrate")).resolve()

mcp = FastMCP("failsafe-validation-tools")

def _github_zip_url(repo_url: str, branch: str) -> str:
    normalized = repo_url.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return f"{normalized}/archive/refs/heads/{branch}.zip"

def _run_command(command: list[str], cwd: Path | None = None, timeout: int = 60) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:]
        }
    except Exception as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool
def ping() -> dict:
    """Health check."""
    return {
        "status": "ok",
        "project_root": str(PROJECT_ROOT),
        "target_repo_url": target_repo_url,
        "target_repo_branch": target_repo_branch
    }

@mcp.tool
def sync_target_repo() -> dict:
    """Download and refresh the target GitHub repo into the local working directory."""
    if not target_repo_url:
        return {
            "ok": False,
            "message": "TARGET_REPO_URL is not configured",
            "project_root": str(project_root)
        }

    zip_url = _github_zip_url(target_repo_url, target_repo_branch)
    parent_dir = project_root.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    if project_root.exists():
        shutil.rmtree(project_root)

    temp_extract_dir = Path(tempfile.mkdtemp(prefix="apicrate_extract_"))

    try:
        with urllib.request.urlopen(zip_url, timeout=60) as response:
            data = response.read()

        with zipfile.ZipFile(io.BytesIO(data)) as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        extracted_dirs = [p for p in temp_extract_dir.iterdir() if p.is_dir()]
        if not extracted_dirs:
            return {
                "ok": False,
                "message": "Downloaded archive did not contain an extracted repository directory",
                "zip_url": zip_url
            }

        extracted_repo_dir = extracted_dirs[0]
        shutil.move(str(extracted_repo_dir), str(project_root))

        return {
            "ok": True,
            "message": "Target repo synced successfully from GitHub archive",
            "project_root": str(project_root),
            "repo_url": target_repo_url,
            "branch": target_repo_branch,
            "zip_url": zip_url
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to download or extract target repo archive",
            "project_root": str(project_root),
            "zip_url": zip_url,
            "error": str(e)
        }

    finally:
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir, ignore_errors=True)


@mcp.tool
def list_project_files() -> list[str]:
    """List top-level files in the target project."""
    if not PROJECT_ROOT.exists():
        return [f"PROJECT_ROOT not found: {PROJECT_ROOT}"]
    return sorted([p.name for p in PROJECT_ROOT.iterdir()])

@mcp.tool
def install_project_dependencies() -> dict:
    """Install Python dependencies for the synced target project."""
    if not project_root.exists():
        return {
            "ok": False,
            "message": "PROJECT_ROOT not found. Run sync_target_repo first.",
            "project_root": str(project_root)
        }

    requirements_file = project_root / "requirements.txt"
    if not requirements_file.exists():
        return {
            "ok": False,
            "message": "requirements.txt not found in target project",
            "project_root": str(project_root),
            "requirements_file": str(requirements_file)
        }

    marker_file = project_root / ".deps_installed"

    if marker_file.exists():
        return {
            "ok": True,
            "message": "Dependencies already installed",
            "project_root": str(project_root),
            "requirements_file": str(requirements_file)
        }

    result = _run_command(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
        cwd=project_root,
        timeout=300
    )

    if result["ok"]:
        marker_file.write_text("installed\n")

    return {
        "project_root": str(project_root),
        "requirements_file": str(requirements_file),
        **result
    }

@mcp.tool
def run_tests() -> dict:
    """Run pytest in the synced target project."""
    if not project_root.exists():
        return {
            "ok": False, 
            "message": "PROJECT_ROOT not found. Run sync_target_repo first.",
            "project_root": str(project_root)
            }
    
    return {
        "project_root": str(project_root),
        **_run_command(["pytest", "-q"], cwd=project_root, timeout=120)
    }

@mcp.tool
def run_linter() -> dict:
    """Run ruff against the synced target project."""
    if not project_root.exists():
        return {
            "ok": False,
            "message": "PROJECT_ROOT not found. Run sync_target_repo first.",
            "project_root": str(project_root)
        }

    return {
        "project_root": str(project_root),
        **_run_command([sys.executable, "-m", "ruff", "check", "."], cwd=project_root, timeout=120)
    }

SUSPICIOUS_SECRET_PATTERNS = [
    "api_key",
    "secret_key",
    "access_key",
    "private_key",
    "bearer ",
    "sk-",
    "aws_secret_access_key",
    "password=",
    "token="
]

@mcp.tool
def run_secret_scan() -> dict:
    """Scan the synced target project for suspicious hardcoded secret patterns."""
    if not project_root.exists():
        return {
            "ok": False,
            "message": "PROJECT_ROOT not found. Run sync_target_repo first.",
            "project_root": str(project_root)
        }

    matches = []

    for path in project_root.rglob("*"):
        if not path.is_file():
            continue

        if any(part.startswith(".venv") for part in path.parts):
            continue

        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".lock"}:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        lower_text = text.lower()
        for pattern in SUSPICIOUS_SECRET_PATTERNS:
            if pattern in lower_text:
                matches.append({
                    "file": str(path.relative_to(project_root)),
                    "pattern": pattern
                })

    return {
        "ok": len(matches) == 0,
        "project_root": str(project_root),
        "matches": matches,
        "message": "No suspicious secret patterns found" if not matches else "Suspicious secret patterns detected"
    }

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
        "allowed_files": sorted(set(allowed)),
        "blocked_files": sorted(set(blocked)),
        "unknown_files": sorted(set(unknown)),
        "allowed_prefixes": ALLOWED_PATCH_PREFIXES,
        "blocked_prefixes": BLOCKED_PATCH_PREFIXES,
        "message": (
            "Patch scope approved"
            if ok
            else "Patch scope rejected because some files are blocked or outside the approved scope"
        ),
    }