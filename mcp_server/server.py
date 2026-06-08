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

ALLOWED_PREFIXES = [
    "app/routes/",
    "app/models.py",
    "tests/",
    "CHANGELOG.md",
    "README.md",
]

BLOCKED_PREFIXES = [
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
TARGET_REPO_DIR = Path(
    os.environ.get("TARGET_REPO_DIR", "./workspace/apicrate")
).resolve()

mcp = FastMCP("failsafe-validation-tools")

def _resolve_repo(workspace=None) -> Path:
    return Path(workspace).resolve() if workspace else TARGET_REPO_DIR


def _repo_exists(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_relative_path(path_str: str) -> Path:
    rel = Path(path_str)
    if rel.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {path_str}")
    if ".." in rel.parts:
        raise ValueError(f"Parent traversal is not allowed: {path_str}")
    return rel


def _normalize(path_str: str) -> str:
    return path_str.replace("\\", "/").lstrip("./")


def _is_allowed_path(path_str: str) -> bool:
    normalized = _normalize(path_str)
    return any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in ALLOWED_PREFIXES
    )


def _is_blocked_path(path_str: str) -> bool:
    normalized = _normalize(path_str)
    return any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in BLOCKED_PREFIXES
    )

def _github_zip_url(repo_url: str, branch: str) -> str:
    normalized = repo_url.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return f"{normalized}/archive/refs/heads/{branch}.zip"

def _run(cmd: list[str], cwd: Path | None = None) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "command": " ".join(cmd),
            "cwd": str(cwd) if cwd else None,
        }
    except FileNotFoundError as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command not found: {e}",
            "command": " ".join(cmd),
            "cwd": str(cwd) if cwd else None,
        }
    except Exception as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "command": " ".join(cmd),
            "cwd": str(cwd) if cwd else None,
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
def install_project_dependencies(workspace=None) -> dict:
    repo = _resolve_repo(workspace)

    if not _repo_exists(repo):
        return {
            "ok": False,
            "message": f"Repository path does not exist: {repo}",
        }

    if (repo / "pyproject.toml").exists():
        if shutil.which("uv"):
            res = _run(["uv", "sync"], cwd=repo)
            return {
                "ok": res["ok"],
                "message": "Dependencies installed with uv." if res["ok"] else "uv sync failed.",
                "workspace": str(repo),
                "result": res,
            }

        res = _run(["python", "-m", "pip", "install", "-e", "."], cwd=repo)
        return {
            "ok": res["ok"],
            "message": "Dependencies installed with pip." if res["ok"] else "pip install failed.",
            "workspace": str(repo),
            "result": res,
        }

    if (repo / "requirements.txt").exists():
        res = _run(["python", "-m", "pip", "install", "-r", "requirements.txt"], cwd=repo)
        return {
            "ok": res["ok"],
            "message": "Dependencies installed from requirements.txt." if res["ok"] else "requirements install failed.",
            "workspace": str(repo),
            "result": res,
        }

    return {
        "ok": True,
        "message": "No dependency install step detected; skipping.",
        "workspace": str(repo),
        "result": {},
    }

@mcp.tool
def run_tests(workspace=None) -> dict:
    repo = _resolve_repo(workspace)

    if not _repo_exists(repo):
        return {
            "ok": False,
            "message": f"Repository path does not exist: {repo}",
        }

    res = _run(["python", "-m", "pytest", "-q"], cwd=repo)

    return {
        "ok": res["ok"],
        "message": "Tests passed." if res["ok"] else "Tests failed.",
        "workspace": str(repo),
        "result": res,
        "stdout": res["stdout"],
        "stderr": res["stderr"],
    }

@mcp.tool
def run_linter(workspace=None) -> dict:
    repo = _resolve_repo(workspace)

    if not _repo_exists(repo):
        return {
            "ok": False,
            "message": f"Repository path does not exist: {repo}",
        }

    if shutil.which("ruff"):
        res = _run(["ruff", "check", "."], cwd=repo)
    else:
        res = _run(["python", "-m", "ruff", "check", "."], cwd=repo)

    return {
        "ok": res["ok"],
        "message": "Lint passed." if res["ok"] else "Lint failed.",
        "workspace": str(repo),
        "result": res,
        "stdout": res["stdout"],
        "stderr": res["stderr"],
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
def run_secret_scan(workspace=None) -> dict:
    repo = _resolve_repo(workspace)

    if not _repo_exists(repo):
        return {
            "ok": False,
            "message": f"Repository path does not exist: {repo}",
        }

    if not shutil.which("gitleaks"):
        return {
            "ok": False,
            "message": "gitleaks is not installed or not available on PATH.",
            "workspace": str(repo),
        }

    res = _run(["gitleaks", "detect", "--no-git", "--source", str(repo)], cwd=repo)

    return {
        "ok": res["ok"],
        "message": "Secret scan passed." if res["ok"] else "Secret scan found issues.",
        "workspace": str(repo),
        "result": res,
        "stdout": res["stdout"],
        "stderr": res["stderr"],
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
            for blocked_prefix in BLOCKED_PREFIXES
        ):
            blocked.append(normalized)
            continue

        if any(
            normalized == allowed_prefix or normalized.startswith(allowed_prefix)
            for allowed_prefix in ALLOWED_PREFIXES
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
        "allowed_prefixes": ALLOWED_PREFIXES,
        "blocked_prefixes": BLOCKED_PREFIXES,
        "message": (
            "Patch scope approved"
            if ok
            else "Patch scope rejected because some files are blocked or outside the approved scope"
        ),
    }

@mcp.tool
def apply_patch_dry_run(files: list[dict]) -> dict:
    baseline = TARGET_REPO_DIR

    if not _repo_exists(baseline):
        return {
            "ok": False,
            "message": f"Baseline repository does not exist: {baseline}",
            "workspace": None,
            "written_files": [],
            "violations": [f"Missing baseline repo: {baseline}"],
        }

    temp_root = Path(tempfile.mkdtemp(prefix="failsafe-dryrun-"))
    workspace = temp_root / "repo"
    shutil.copytree(baseline, workspace)

    written_files = []
    violations = []

    for item in files:
        path = item.get("path")
        content = item.get("content", "")

        if not path:
            violations.append("Missing file path in patch draft item.")
            continue

        normalized = _normalize(path)

        if _is_blocked_path(normalized):
            violations.append(f"Blocked path in patch draft: {normalized}")
            continue

        if not _is_allowed_path(normalized):
            violations.append(f"Out-of-scope path in patch draft: {normalized}")
            continue

        try:
            rel = _safe_relative_path(normalized)
            dest = workspace / rel
            _ensure_parent(dest)
            dest.write_text(content, encoding="utf-8")
            written_files.append(normalized)
        except Exception as e:
            violations.append(f"{normalized}: {e}")

    ok = len(violations) == 0

    return {
        "ok": ok,
        "message": "Dry-run patch applied." if ok else "Dry-run patch application had violations.",
        "workspace": str(workspace),
        "written_files": written_files,
        "violations": violations,
    }

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)