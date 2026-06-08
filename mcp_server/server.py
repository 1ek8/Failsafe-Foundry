from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastmcp import FastMCP


mcp = FastMCP("failsafe-foundry")


TARGET_REPO_URL = os.environ.get("TARGET_REPO_URL", "").strip()
TARGET_REPO_REF = os.environ.get("TARGET_REPO_REF", "main").strip()
TARGET_REPO_DIR = Path(os.environ.get("TARGET_REPO_DIR", "./workspace/apicrate")).resolve()

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
    "secrets/",
]


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


def _resolve_repo(workspace=None) -> Path:
    if workspace:
        return Path(workspace).resolve()
    return TARGET_REPO_DIR


def _repo_exists(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_relative_path(p: str) -> Path:
    rel = Path(p)
    if rel.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {p}")
    if ".." in rel.parts:
        raise ValueError(f"Parent traversal is not allowed: {p}")
    return rel


def _is_allowed_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    return any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in ALLOWED_PREFIXES
    )


def _is_blocked_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    return any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in BLOCKED_PREFIXES
    )


@mcp.tool
def sync_target_repo() -> dict:
    """
    Clone or refresh the target repository into the baseline working directory.
    """
    if not TARGET_REPO_URL:
        return {
            "ok": False,
            "message": "TARGET_REPO_URL is not set.",
            "repo_dir": str(TARGET_REPO_DIR),
        }

    TARGET_REPO_DIR.parent.mkdir(parents=True, exist_ok=True)

    if not _repo_exists(TARGET_REPO_DIR / ".git"):
        if TARGET_REPO_DIR.exists():
            shutil.rmtree(TARGET_REPO_DIR)

        clone_result = _run(
            ["git", "clone", "--branch", TARGET_REPO_REF, TARGET_REPO_URL, str(TARGET_REPO_DIR)]
        )
        return {
            "ok": clone_result["ok"],
            "message": "Repository cloned." if clone_result["ok"] else "Repository clone failed.",
            "repo_dir": str(TARGET_REPO_DIR),
            "result": clone_result,
        }

    fetch_result = _run(["git", "fetch", "origin"], cwd=TARGET_REPO_DIR)
    reset_result = _run(["git", "reset", "--hard", f"origin/{TARGET_REPO_REF}"], cwd=TARGET_REPO_DIR)
    clean_result = _run(["git", "clean", "-fd"], cwd=TARGET_REPO_DIR)

    ok = fetch_result["ok"] and reset_result["ok"] and clean_result["ok"]
    return {
        "ok": ok,
        "message": "Repository synced." if ok else "Repository sync failed.",
        "repo_dir": str(TARGET_REPO_DIR),
        "result": {
            "fetch": fetch_result,
            "reset": reset_result,
            "clean": clean_result,
        },
    }


@mcp.tool
def list_project_files(workspace=None, max_entries: int = 200) -> dict:
    """
    List project files for repo grounding. Uses workspace if provided, else baseline repo.
    """
    repo = _resolve_repo(workspace)
    if not _repo_exists(repo):
        return {
            "ok": False,
            "message": f"Repository path does not exist: {repo}",
            "files": [],
        }

    files = []
    for path in sorted(repo.rglob("*")):
        if ".git" in path.parts:
            continue
        if path.is_file():
            files.append(str(path.relative_to(repo)).replace("\\", "/"))
        if len(files) >= max_entries:
            break

    return {
        "ok": True,
        "message": f"Found {len(files)} files.",
        "workspace": str(repo),
        "files": files,
        "result": files,
    }


@mcp.tool
def validate_patch_scope(files: list[str]) -> dict:
    """
    Validate whether requested patch paths stay inside the approved scope.
    """
    violations = []
    normalized_files = []

    for raw in files:
        normalized = raw.replace("\\", "/").lstrip("./")
        normalized_files.append(normalized)

        if _is_blocked_path(normalized):
            violations.append(f"Blocked path: {normalized}")
            continue

        if not _is_allowed_path(normalized):
            violations.append(f"Out-of-scope path: {normalized}")

    return {
        "ok": len(violations) == 0,
        "message": "Patch scope is valid." if not violations else "Patch scope violations detected.",
        "files": normalized_files,
        "violations": violations,
        "result": {
            "ok": len(violations) == 0,
            "violations": violations,
        },
    }


@mcp.tool
def install_project_dependencies(workspace=None) -> dict:
    """
    Install project dependencies in the target workspace if supported by the repo.
    """
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

        if shutil.which("pip"):
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
def apply_patch_dry_run(files: list[dict]) -> dict:
    """
    Create an isolated workspace by copying the baseline repo and writing generated files into it.
    """
    baseline = TARGET_REPO_DIR
    if not _repo_exists(baseline):
        return {
            "ok": False,
            "message": f"Baseline repository does not exist: {baseline}",
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

        normalized = path.replace("\\", "/").lstrip("./")

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
        "result": {
            "ok": ok,
            "workspace": str(workspace),
            "written_files": written_files,
            "violations": violations,
        },
    }


@mcp.tool
def run_linter(workspace=None) -> dict:
    """
    Run lint checks against the provided workspace or the baseline repo.
    """
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


@mcp.tool
def run_tests(workspace=None) -> dict:
    """
    Run tests against the provided workspace or the baseline repo.
    """
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
def run_secret_scan(workspace=None) -> dict:
    """
    Run a secrets scan against the provided workspace or the baseline repo.
    """
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


if __name__ == "__main__":
    mcp.run()