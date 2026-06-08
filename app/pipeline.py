from pathlib import Path
from app.mcp_client import call_mcp_tool
from app.agent_client import plan_patch
from app.schemas import FeatureTicket, PatchPlan, ToolResult, PipelineReport
from app.reporter import render_markdown_report


def normalize_tool_payload(result) -> dict:
    if isinstance(result, dict):
        return result

    if hasattr(result, "model_dump"):
        try:
            dumped = result.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    payload = {}

    if hasattr(result, "structuredContent"):
        payload["structuredContent"] = getattr(result, "structuredContent")

    if hasattr(result, "structured_content"):
        payload["structuredContent"] = getattr(result, "structured_content")

    if hasattr(result, "content"):
        payload["content"] = getattr(result, "content")

    if hasattr(result, "isError"):
        payload["isError"] = getattr(result, "isError")

    if hasattr(result, "is_error"):
        payload["isError"] = getattr(result, "is_error")

    if not payload:
        payload["raw"] = str(result)

    return payload


def extract_ok(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False

    if "ok" in payload:
        return bool(payload["ok"])

    structured = payload.get("structuredContent")
    if isinstance(structured, dict):
        if "ok" in structured:
            return bool(structured["ok"])
        if "result" in structured and isinstance(structured["result"], dict) and "ok" in structured["result"]:
            return bool(structured["result"]["ok"])

    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                if '"ok":true' in text.lower() or '"ok": true' in text.lower():
                    return True
                if '"ok":false' in text.lower() or '"ok": false' in text.lower():
                    return False

    return False


def summarize_payload(payload: dict) -> str:
    if not isinstance(payload, dict):
        return str(payload)

    structured = payload.get("structuredContent")
    if isinstance(structured, dict):
        if "message" in structured:
            return str(structured["message"])
        if "stdout" in structured and structured["stdout"]:
            return str(structured["stdout"])[:300]
        if "result" in structured:
            return str(structured["result"])[:300]

    content = payload.get("content")
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        if texts:
            return "\n".join(texts)[:300]

    if content:
        return str(content)[:300]

    return "No details available."


def review_patch_plan(ticket: FeatureTicket, patch_plan: PatchPlan) -> tuple[bool, list[str]]:
    reasons = []

    text = f"{ticket.title}\n{ticket.summary}\n{patch_plan.summary}\n" + "\n".join(patch_plan.risk_notes)
    lower = text.lower()
    files = [f.lower() for f in patch_plan.files_to_touch]

    risky_phrases = [
        "debug endpoint",
        "expose config",
        "config values",
        "disable auth",
        "bypass auth",
        "raw secrets",
        "environment variables",
        "admin backdoor",
        "shell command",
        "remote execution",
    ]

    blocked_paths = [
        "infra/",
        "deploy/",
        ".github/",
        ".env",
        "secrets/",
    ]

    if any(phrase in lower for phrase in risky_phrases):
        reasons.append("Patch plan contains risky intent requiring manual review.")

    if any(any(path.startswith(prefix) or path == prefix for prefix in blocked_paths) for path in files):
        reasons.append("Patch plan touches blocked paths.")

    if any("debug.py" in path for path in files):
        reasons.append("Debug endpoints are not auto-approved by policy.")

    return len(reasons) == 0, reasons


def build_repo_context(files_payload: dict) -> str:
    result = []

    structured = files_payload.get("structuredContent")
    if isinstance(structured, dict):
        if "result" in structured and isinstance(structured["result"], list):
            result = structured["result"]
        elif "files" in structured and isinstance(structured["files"], list):
            result = structured["files"]

    top_level_files = "\n".join(f"- {item}" for item in result) if result else "- unknown"

    return f"""
Top-level files in target repo:
{top_level_files}

Allowed patch scope prefixes:
- app/routes/
- app/models.py
- tests/
- CHANGELOG.md
- README.md

Blocked prefixes:
- .github/
- infra/
- deploy/
- .env
- .env.
- secrets/

Important:
- This is a Python/FastAPI codebase.
- Prefer app/routes/projects.py, tests/test_projects.py, and CHANGELOG.md for a project-endpoint request.
""".strip()


def build_report(ticket: FeatureTicket) -> PipelineReport:
    tool_results = []

    sync_payload = normalize_tool_payload(call_mcp_tool("sync_target_repo", {}))
    sync_ok = extract_ok(sync_payload)
    tool_results.append(
        ToolResult(name="sync_target_repo", ok=sync_ok, payload=sync_payload)
    )

    deps_payload = normalize_tool_payload(call_mcp_tool("install_project_dependencies", {}))
    deps_ok = extract_ok(deps_payload)
    tool_results.append(
        ToolResult(name="install_project_dependencies", ok=deps_ok, payload=deps_payload)
    )

    files_payload = normalize_tool_payload(call_mcp_tool("list_project_files", {}))
    files_ok = True
    tool_results.append(
        ToolResult(name="list_project_files", ok=files_ok, payload=files_payload)
    )

    repo_context = build_repo_context(files_payload)
    plan_data = plan_patch(
        f"Title: {ticket.title}\nSummary: {ticket.summary}",
        repo_context=repo_context,
    )
    patch_plan = PatchPlan(**plan_data)
    plan_ok, plan_review_reasons = review_patch_plan(ticket, patch_plan)

    if not plan_ok:
        scope_payload = {
            "structuredContent": {
                "message": "Skipped because policy review failed before scope validation."
            }
        }
        scope_ok = False
        lint_ok = False
        secrets_ok = False
        tests_ok = False

        tool_results.append(
            ToolResult(name="validate_patch_scope", ok=False, payload=scope_payload)
        )
        tool_results.append(
            ToolResult(
                name="run_linter",
                ok=False,
                payload={"structuredContent": {"message": "Skipped because policy review failed."}},
            )
        )
        tool_results.append(
            ToolResult(
                name="run_secret_scan",
                ok=False,
                payload={"structuredContent": {"message": "Skipped because policy review failed."}},
            )
        )
        tool_results.append(
            ToolResult(
                name="run_tests",
                ok=False,
                payload={"structuredContent": {"message": "Skipped because policy review failed."}},
            )
        )

    else:
        scope_payload = normalize_tool_payload(
            call_mcp_tool("validate_patch_scope", {"files": patch_plan.files_to_touch})
        )
        scope_ok = extract_ok(scope_payload)
        tool_results.append(
            ToolResult(name="validate_patch_scope", ok=scope_ok, payload=scope_payload)
        )

        if scope_ok:
            lint_payload = normalize_tool_payload(call_mcp_tool("run_linter", {}))
            lint_ok = extract_ok(lint_payload)
            tool_results.append(
                ToolResult(name="run_linter", ok=lint_ok, payload=lint_payload)
            )

            secrets_payload = normalize_tool_payload(call_mcp_tool("run_secret_scan", {}))
            secrets_ok = extract_ok(secrets_payload)
            tool_results.append(
                ToolResult(name="run_secret_scan", ok=secrets_ok, payload=secrets_payload)
            )

            tests_payload = normalize_tool_payload(call_mcp_tool("run_tests", {}))
            tests_ok = extract_ok(tests_payload)
            tool_results.append(
                ToolResult(name="run_tests", ok=tests_ok, payload=tests_payload)
            )
        else:
            lint_ok = False
            secrets_ok = False
            tests_ok = False

            tool_results.append(
                ToolResult(
                    name="run_linter",
                    ok=False,
                    payload={"structuredContent": {"message": "Skipped because patch scope failed."}},
                )
            )
            tool_results.append(
                ToolResult(
                    name="run_secret_scan",
                    ok=False,
                    payload={"structuredContent": {"message": "Skipped because patch scope failed."}},
                )
            )
            tool_results.append(
                ToolResult(
                    name="run_tests",
                    ok=False,
                    payload={"structuredContent": {"message": "Skipped because patch scope failed."}},
                )
            )

    reasons = []

    if not sync_ok:
        reasons.append(f"sync_target_repo failed: {summarize_payload(sync_payload)}")
    if not deps_ok:
        reasons.append(f"install_project_dependencies failed: {summarize_payload(deps_payload)}")
    if not scope_ok:
        reasons.append(f"validate_patch_scope failed: {summarize_payload(scope_payload)}")
    if scope_ok and not lint_ok:
        reasons.append("run_linter failed.")
    if scope_ok and not secrets_ok:
        reasons.append("run_secret_scan failed.")
    if scope_ok and not tests_ok:
        reasons.append("run_tests failed.")

    reasons.extend(plan_review_reasons)

    if not sync_ok or not deps_ok:
        outcome = "docs-only"
        if not reasons:
            reasons = ["Repository preparation failed; downgrade to documentation-only mode."]
    elif not scope_ok:
        outcome = "blocked"
        if not reasons:
            reasons = ["Patch scope violated policy."]
    elif not secrets_ok:
        outcome = "blocked"
        if not reasons:
            reasons = ["Secret scan detected risky patterns."]
    elif not lint_ok or not tests_ok:
        outcome = "docs-only"
        if not reasons:
            reasons = ["Validation failed; downgrade to documentation-only mode."]
    else:
        outcome = "approved-draft"
        reasons = ["All validation checks passed."]

    release_note = (
        "Draft patch validated successfully and is ready for the next coding stage."
        if outcome == "approved-draft"
        else "Patch not cleared for automated release; human review or restricted fallback required."
    )

    return PipelineReport(
        request_title=ticket.title,
        outcome=outcome,
        reasons=reasons,
        patch_plan=patch_plan,
        tool_results=tool_results,
        release_note=release_note,
    )


def save_report(report: PipelineReport):
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    slug = report.request_title.lower().replace(" ", "-").replace("/", "-")
    path = reports_dir / f"{slug}.md"
    path.write_text(render_markdown_report(report), encoding="utf-8")
    return path