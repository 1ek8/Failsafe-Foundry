from app.schemas import FeatureTicket, ToolResult, PipelineReport


def decide_outcome(scope_ok: bool, lint_ok: bool, secrets_ok: bool, tests_ok: bool):
    if not scope_ok:
        return "blocked", ["Patch scope violated policy."]
    if not secrets_ok:
        return "blocked", ["Secret scan detected risky patterns."]
    if not lint_ok or not tests_ok:
        return "docs-only", ["Validation failed; downgrade to documentation-only mode."]
    return "approved-draft", ["All validation checks passed."]