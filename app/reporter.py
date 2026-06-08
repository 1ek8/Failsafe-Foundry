from datetime import datetime
from app.schemas import PipelineReport


def render_markdown_report(report: PipelineReport) -> str:
    lines = [
        "# Failsafe Foundry Run Report",
        "",
        f"**Request:** {report.request_title}",
        f"**Outcome:** {report.outcome}",
        "",
        "## Reasons",
    ]

    for reason in report.reasons:
        lines.append(f"- {reason}")

    lines.extend([
        "",
        "## Patch Plan",
        report.patch_plan.summary,
        "",
        "### Files To Touch",
    ])

    for f in report.patch_plan.files_to_touch:
        lines.append(f"- {f}")

    lines.extend(["", "### Risk Notes"])
    for note in report.patch_plan.risk_notes:
        lines.append(f"- {note}")

    lines.extend(["", "## Tool Results"])
    for t in report.tool_results:
        lines.append(f"- **{t.name}**: {'PASS' if t.ok else 'FAIL'}")

    lines.extend([
        "",
        "## Release Note",
        report.release_note,
        "",
        f"_Generated at {datetime.utcnow().isoformat()}Z_"
    ])

    return "\n".join(lines)