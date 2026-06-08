import json
import re
from openai import OpenAI
from app.config import TFY_API_TOKEN, GATEWAY_BASE_URL, MODEL

client = OpenAI(
    base_url=GATEWAY_BASE_URL,
    api_key=TFY_API_TOKEN,
)

PLAN_SYSTEM_PROMPT = """
You are the planning brain of Failsafe Foundry.

Your job is to propose a SAFE patch plan for a Python/FastAPI repository.

Return JSON only with this exact schema:
{
  "summary": "string",
  "files_to_touch": ["string"],
  "risk_notes": ["string"]
}

Rules:
- The target repository is a Python/FastAPI app.
- Only propose files that plausibly fit the repository context provided by the user.
- Prefer these safe locations when relevant:
  - app/routes/
  - app/models.py
  - tests/
  - CHANGELOG.md
  - README.md
- Never suggest infra/, deploy/, .github/, secrets/, .env, or environment/config file changes unless the request explicitly requires them.
- Keep file list minimal and realistic.
- No markdown fences.
- Output JSON only.
"""

PATCH_SYSTEM_PROMPT = """
You are the code generation agent for Failsafe Foundry.

Return JSON only with this exact schema:
{
  "summary": "string",
  "files": [
    {
      "path": "string",
      "content": "string"
    }
  ],
  "release_note": "string"
}

Rules:
- The target repository is a Python/FastAPI app.
- Only generate files explicitly listed in the approved patch plan.
- Do not generate infra/, deploy/, .github/, secrets/, or .env changes.
- Keep code minimal, realistic, and syntactically valid.
- No markdown fences.
- Output JSON only.
"""


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()

    if not text:
        raise ValueError("Model returned empty content")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError(f"Could not parse JSON from model output: {text}")


def fallback_plan(ticket_text: str) -> dict:
    lower = ticket_text.lower()

    files = ["CHANGELOG.md"]

    if "project" in lower:
        files = [
            "app/routes/projects.py",
            "tests/test_projects.py",
            "CHANGELOG.md",
        ]

    return {
        "summary": "Create a minimal safe patch plan for the requested FastAPI feature.",
        "files_to_touch": files,
        "risk_notes": [
            "Limit changes to approved application and test files.",
            "Avoid infra, deploy, secret, and environment modifications.",
        ],
    }


def fallback_patch_draft(patch_plan: dict) -> dict:
    approved_files = patch_plan.get("files_to_touch", [])

    files = []
    for path in approved_files:
        if path == "CHANGELOG.md":
            files.append(
                {
                    "path": "CHANGELOG.md",
                    "content": "## Unreleased\n- Added draft update from Failsafe Foundry.\n",
                }
            )

    return {
        "summary": "Fallback draft patch generated with minimal safe content.",
        "files": files,
        "release_note": "Generated a minimal fallback patch draft.",
    }


def plan_patch(ticket_text: str, repo_context: str) -> dict:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PLAN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{ticket_text}\n\nRepository context:\n{repo_context}",
            },
        ],
        extra_headers={
            "X-TFY-METADATA": "{}",
            "X-TFY-LOGGING-CONFIG": '{"enabled": true}',
        },
        temperature=0.2,
    )

    content = resp.choices[0].message.content or ""

    try:
        parsed = _extract_json_object(content)

        if not isinstance(parsed, dict):
            return fallback_plan(ticket_text)

        if "summary" not in parsed or "files_to_touch" not in parsed or "risk_notes" not in parsed:
            return fallback_plan(ticket_text)

        if not isinstance(parsed["files_to_touch"], list) or not isinstance(parsed["risk_notes"], list):
            return fallback_plan(ticket_text)

        return parsed

    except Exception:
        return fallback_plan(ticket_text)


def generate_patch_draft(ticket_text: str, patch_plan: dict, repo_context: str) -> dict:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PATCH_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{ticket_text}\n\n"
                    f"Approved patch plan:\n{json.dumps(patch_plan, indent=2)}\n\n"
                    f"Repository context:\n{repo_context}"
                ),
            },
        ],
        extra_headers={
            "X-TFY-METADATA": "{}",
            "X-TFY-LOGGING-CONFIG": '{"enabled": true}',
        },
        temperature=0.2,
    )

    content = resp.choices[0].message.content or ""

    try:
        parsed = _extract_json_object(content)

        if not isinstance(parsed, dict):
            return fallback_patch_draft(patch_plan)

        if "summary" not in parsed or "files" not in parsed or "release_note" not in parsed:
            return fallback_patch_draft(patch_plan)

        if not isinstance(parsed["files"], list):
            return fallback_patch_draft(patch_plan)

        approved = set(patch_plan.get("files_to_touch", []))
        filtered_files = []

        for item in parsed["files"]:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            file_content = item.get("content", "")
            if isinstance(path, str) and path in approved and isinstance(file_content, str):
                filtered_files.append({"path": path, "content": file_content})

        if not filtered_files:
            return fallback_patch_draft(patch_plan)

        return {
            "summary": parsed["summary"],
            "files": filtered_files,
            "release_note": parsed["release_note"],
        }

    except Exception:
        return fallback_patch_draft(patch_plan)