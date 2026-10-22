"""Thin artifact scaffolding and verification for the prompt-driven AutoDesign flow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .effects import check_design
from .io import read_json, write_text

STATE_PATTERN = re.compile(
    r"^\s*\|\s*Current stage\s*\|\s*([A-Z0-9_]+)\s*\|\s*$",
    re.MULTILINE,
)
AUDIT_VERDICT_PATTERN = re.compile(
    r"^\s*Verdict\s*:\s*(PASS|FAIL)\s*$", re.IGNORECASE | re.MULTILINE
)
REVISION_ID_PATTERN = re.compile(r"^\s*Revision ID\s*:\s*([A-Za-z0-9._-]+)\s*$", re.MULTILINE)
METHOD_REVISION_DECISION_PATTERN = re.compile(
    r"^\s*Decision\s*:\s*"
    r"(APPROVE_MINIMAL_METHOD_REVISION|APPROVE_EXCEPTION_METHOD_REVISION|"
    r"REJECT_METHOD_REVISION|ABANDON_IDEA)\s*$",
    re.MULTILINE,
)
STAGE_ORDER = (
    "INPUT_READY",
    "EXPERIMENT_DESIGN_READY",
    "IMPLEMENTATION_READY",
    "EXECUTION_COMPLETE",
    "RESULT_DIAGNOSIS_READY",
    "INTEGRITY_AUDIT_PASS",
    "COMPLETE",
)
KNOWN_STAGES = (
    "INPUT_READY",
    "EXPERIMENT_DESIGN_READY",
    "WAITING_FOR_R0",
    "R0_PASSED",
    "R0_FAILED_RETURN_TO_DESIGN",
    "WAITING_FOR_METHOD_REVISION_APPROVAL",
    "IMPLEMENTATION_READY",
    "EXECUTION_IN_PROGRESS",
    "EXECUTION_COMPLETE",
    "RESULT_DIAGNOSIS_READY",
    "INTEGRITY_AUDIT_PASS",
    "COMPLETE",
    "IDEA_ABANDONED",
)
STAGE_REQUIREMENTS = {
    "INPUT_READY": ("AUTODESIGN_STATE.md", "input_brief.md"),
    "EXPERIMENT_DESIGN_READY": ("experiment_design.md", "expected_effects.json"),
    "IMPLEMENTATION_READY": (
        "implementation_notes.md",
        "generated_project",
        "command_plan.json",
        "experiment_schedule.json",
        "result_contract.json",
    ),
    "EXECUTION_COMPLETE": ("execution_record.json", "effect_comparison.md"),
    "RESULT_DIAGNOSIS_READY": (
        "result_summary.json",
        "result_diagnosis.md",
        "result_route.md",
    ),
    "INTEGRITY_AUDIT_PASS": ("integrity_audit.md",),
    "COMPLETE": (),
}
NEXT_ACTION = {
    "INPUT_READY": "design",
    "EXPERIMENT_DESIGN_READY": "run",
    "WAITING_FOR_R0": "run",
    "R0_PASSED": "design",
    "R0_FAILED_RETURN_TO_DESIGN": "design",
    "WAITING_FOR_METHOD_REVISION_APPROVAL": "orchestration",
    "IMPLEMENTATION_READY": "run",
    "EXECUTION_IN_PROGRESS": "run",
    "EXECUTION_COMPLETE": "diagnosis",
    "RESULT_DIAGNOSIS_READY": "orchestration",
    "INTEGRITY_AUDIT_PASS": "orchestration",
    "COMPLETE": "none",
    "IDEA_ABANDONED": "none",
}
STATE_ARTIFACTS = (
    ("input_brief.md", "normalized AutoSearch handoff"),
    ("experiment_design.md", "accepted design or provisional R0-gated plan"),
    ("expected_effects.json", "design-time simulated targets and thresholds"),
    ("r0_plan.md", "R0 gate plan when design readiness is provisional"),
    ("r0_record.json", "observed R0 decision when an R0 gate was required"),
    ("implementation_notes.md", "implementation handoff"),
    ("generated_project", "runnable experiment project"),
    ("command_plan.json", "ordered execution commands"),
    ("experiment_schedule.json", "expected result cells"),
    ("result_contract.json", "primary observed result path"),
    ("execution_record.json", "literal execution evidence"),
    ("breakpoint_recovery.md", "execution-breakpoint recovery ledger"),
    ("method_revision_request.md", "unresolved execution breakpoint request"),
    ("method_revision_proposal.md", "minimal method revision awaiting approval"),
    ("method_revision_decision.md", "literal user decision for one revision ID"),
    ("idea_abandonment.md", "terminal user decision to abandon the Idea"),
    ("result_summary.json", "validated result aggregates"),
    ("effect_comparison.md", "observed versus simulated-target outcomes"),
    ("result_diagnosis.md", "scientific interpretation"),
    ("result_route.md", "iteration, tuning, stop, or report dispatch"),
    ("integrity_audit.md", "final claim-evidence audit"),
)

LAST_COMPLETED_STAGE = {
    "WAITING_FOR_R0": "INPUT_READY",
    "R0_FAILED_RETURN_TO_DESIGN": "INPUT_READY",
    "WAITING_FOR_METHOD_REVISION_APPROVAL": "EXPERIMENT_DESIGN_READY",
    "EXECUTION_IN_PROGRESS": "IMPLEMENTATION_READY",
    "IDEA_ABANDONED": "EXPERIMENT_DESIGN_READY",
}


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _markdown_table_cell(value: str) -> str:
    """Keep agent-provided text inside one Markdown table cell."""

    return (
        str(value)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("|", "&#124;")
        .replace("\n", "<br>")
    )


def _state_field_pattern(field: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\s*\|\s*{re.escape(field)}\s*\|\s*([^|]*?)\s*\|\s*$",
        re.MULTILINE,
    )


def _replace_state_field(text: str, field: str, value: str) -> str:
    pattern = _state_field_pattern(field)
    if field == "Next action" and not pattern.search(text):
        # Existing AutoDesign runs use this label; update it only on an explicit state write.
        text = _state_field_pattern("Next Skill").sub("| Next action | pending |", text, count=1)
    if not pattern.search(text):
        raise ValueError(
            f"AUTODESIGN_STATE.md is missing the {field!r} row; restore it or run init"
        )
    return pattern.sub(f"| {field} | {value} |", text, count=1)


def _audit_verdict(run_path: Path) -> str | None:
    audit_path = run_path / "integrity_audit.md"
    if not audit_path.is_file():
        return None
    match = AUDIT_VERDICT_PATTERN.search(audit_path.read_text(encoding="utf-8"))
    return match.group(1).upper() if match else None


def _method_revision_decision(run_path: Path) -> tuple[str, str]:
    proposal_path = run_path / "method_revision_proposal.md"
    decision_path = run_path / "method_revision_decision.md"
    if not proposal_path.is_file() or not decision_path.is_file():
        raise ValueError(
            "method revision requires method_revision_proposal.md and method_revision_decision.md"
        )
    proposal_match = REVISION_ID_PATTERN.search(proposal_path.read_text(encoding="utf-8"))
    decision_text = decision_path.read_text(encoding="utf-8")
    decision_id_match = REVISION_ID_PATTERN.search(decision_text)
    decision_match = METHOD_REVISION_DECISION_PATTERN.search(decision_text)
    if not proposal_match or not decision_id_match or not decision_match:
        raise ValueError(
            "method revision proposal and decision require literal Revision ID and Decision rows"
        )
    proposal_id = proposal_match.group(1)
    decision_id = decision_id_match.group(1)
    if proposal_id != decision_id:
        raise ValueError(
            f"method revision decision ID {decision_id!r} does not match proposal "
            f"ID {proposal_id!r}"
        )
    return proposal_id, decision_match.group(1)


def _render_input_brief(input_path: Path) -> str:
    """Render input_brief.md from an AutoSearch handoff file.

    Accepts either a JSON handoff object or free-form natural-language text. JSON must
    carry motivation and contribution; benchmark is optional and becomes a literal lock
    when supplied. Additional keys are preserved verbatim in an extra section so that
    upstream schema drift never silently drops user-supplied input. Natural-language
    input is passed through untouched for the design stage to normalize.
    """

    raw = input_path.read_text(encoding="utf-8").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return (
            "# Input Brief\n\n"
            "## Handoff source\n\n"
            f"Channel: natural language file `{input_path.name}`\n\n"
            "## Original natural-language input\n\n"
            f"{raw}\n\n"
            "Normalize this into literal Motivation and Contribution sections, preserve any "
            "supplied Benchmark as optional input, and have the design "
            "stage select or design the benchmark when it is absent.\n"
        )
    if not isinstance(payload, dict):
        raise TypeError("AutoSearch handoff JSON must contain an object")
    motivation = payload.get("motivation")
    contribution = payload.get("contribution", payload.get("contributions"))
    benchmark = payload.get("benchmark")
    missing = [
        name
        for name, value in (
            ("motivation", motivation),
            ("contribution", contribution),
        )
        if value in (None, "", [], {})
    ]
    if missing:
        raise ValueError(f"AutoSearch handoff is missing: {', '.join(missing)}")
    constraints = benchmark.get("constraints", {}) if isinstance(benchmark, dict) else {}
    benchmark_section = (
        f"## Benchmark input (literal)\n\n```json\n{_json_block(benchmark)}\n```\n\n"
        if benchmark not in (None, "", [], {})
        else (
            "## Benchmark input (not supplied)\n\n"
            "AutoDesign must select or design a contribution-complete benchmark portfolio; "
            "there is no user benchmark lock.\n\n"
        )
    )
    extra = {
        key: value
        for key, value in payload.items()
        if key not in {"schema_version", "motivation", "contribution", "contributions", "benchmark"}
    }
    extra_section = (
        f"## Additional user-supplied input\n\n```json\n{_json_block(extra)}\n```\n\n"
        if extra
        else ""
    )
    return (
        "# Input Brief\n\n"
        "## Handoff source\n\n"
        f"Channel: AutoSearch handoff file `{input_path.name}`\n\n"
        "## Motivation (literal)\n\n"
        f"{motivation}\n\n"
        "## Contribution (literal)\n\n"
        f"```json\n{_json_block(contribution)}\n```\n\n"
        f"{benchmark_section}"
        f"{extra_section}"
        "## Explicit user locks\n\n"
        f"```json\n{_json_block(constraints)}\n```\n\n"
        "Defaults not present in the original handoff are autonomous design choices, not locks.\n"
    )


def _render_state(run_name: str) -> str:
    return f"""# AutoDesign State

| Field | Value |
| --- | --- |
| Pipeline | AutoDesign design-then-run v2 |
| Run | {run_name} |
| Current stage | INPUT_READY |
| Last completed stage | INPUT_READY |
| Blocking condition | none |
| Next action | design |
| Accepted route | pending |
| Execution target | pending |
| Primary result | pending |
| Method revision limit | 2 |

## Accepted inputs

- Input brief: `input_brief.md`
- Explicit locks: copied from the AutoSearch handoff only

## Current artifacts

| Artifact | Status | Decision use |
| --- | --- | --- |
| `input_brief.md` | ready | experiment design input |

## History

| Round | From | To | Changed input | Literal result | Next action |
| ---: | --- | --- | --- | --- | --- |
| 0 | new | INPUT_READY | `input_brief.md` | handoff accepted | run experiment design |
"""


def _refresh_state_snapshot(text: str, run_path: Path, stage: str) -> str:
    """Refresh derived state fields without turning Markdown research into a schema."""

    if not (run_path / "experiment_design.md").is_file():
        route = "pending"
    elif stage == "WAITING_FOR_R0":
        route = "provisional in `experiment_design.md`; awaiting R0"
    elif stage == "R0_FAILED_RETURN_TO_DESIGN":
        route = "R0 rejected; design revision required"
    elif stage == "R0_PASSED":
        route = "R0 outcome recorded; awaiting revised design acceptance"
    elif stage == "WAITING_FOR_METHOD_REVISION_APPROVAL":
        provisional = re.search(r"(?m)^\s*\|\s*Last completed stage\s*\|\s*INPUT_READY\s*\|", text)
        route = ("provisional design retained; protocol revision awaits human approval" if provisional else "accepted design retained; minimal method revision awaits human approval")
    elif stage == "IDEA_ABANDONED":
        route = "current Idea abandoned by user decision"
    else:
        route = "accepted in `experiment_design.md`"
    execution_target = (
        "`generated_project/` via `command_plan.json`"
        if (run_path / "generated_project").is_dir() and (run_path / "command_plan.json").is_file()
        else "pending"
    )
    primary_result = (
        "recorded in `result_summary.json`"
        if (run_path / "result_summary.json").is_file()
        else "pending"
    )
    blocking = {
        "WAITING_FOR_R0": "observed R0 result required",
        "R0_FAILED_RETURN_TO_DESIGN": "experiment design revision required",
        "WAITING_FOR_METHOD_REVISION_APPROVAL": "human method-revision decision required",
        "EXECUTION_IN_PROGRESS": "remaining command stages required",
        "IDEA_ABANDONED": "terminal: current Idea abandoned",
    }.get(stage, "none")
    replacements = {
        "Blocking condition": blocking,
        "Accepted route": route,
        "Execution target": execution_target,
        "Primary result": primary_result,
    }
    for field, value in replacements.items():
        text = _replace_state_field(text, field, value)
    rows = [
        f"| `{relative}` | {'ready' if (run_path / relative).exists() else 'pending'} | {purpose} |"
        for relative, purpose in STATE_ARTIFACTS
    ]
    artifact_section = (
        "## Current artifacts\n\n"
        "| Artifact | Status | Decision use |\n"
        "| --- | --- | --- |\n" + "\n".join(rows) + "\n\n"
    )
    return re.sub(
        r"## Current artifacts\n.*?(?=## History)",
        artifact_section,
        text,
        flags=re.DOTALL,
    )


def initialize_run(input_path: str | Path, run_dir: str | Path) -> dict[str, Any]:
    source = Path(input_path)
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    brief = _render_input_brief(source)
    brief_path = run_path / "input_brief.md"
    state_path = run_path / "AUTODESIGN_STATE.md"
    if brief_path.is_file() and brief_path.read_text(encoding="utf-8") != brief:
        raise ValueError(
            "input_brief.md already exists with different input; use a new run directory"
        )
    write_text(brief_path, brief)
    if not state_path.is_file():
        write_text(state_path, _render_state(run_path.name))
    return inspect_run(run_path)


def read_current_stage(run_dir: str | Path) -> str:
    state_path = Path(run_dir) / "AUTODESIGN_STATE.md"
    if not state_path.is_file():
        raise ValueError("AUTODESIGN_STATE.md is missing; run init first")
    match = STATE_PATTERN.search(state_path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("AUTODESIGN_STATE.md has no canonical Current stage row")
    stage = match.group(1)
    if stage not in KNOWN_STAGES:
        raise ValueError(f"Unknown prompt-driven stage: {stage}")
    return stage


def repair_state(run_dir: str | Path) -> dict[str, Any]:
    """Canonicalize repairable state-table whitespace and refresh derived rows."""

    run_path = Path(run_dir)
    state_path = run_path / "AUTODESIGN_STATE.md"
    stage = read_current_stage(run_path)
    text = state_path.read_text(encoding="utf-8")
    text = _replace_state_field(text, "Current stage", stage)
    preserve_provisional = stage == "WAITING_FOR_METHOD_REVISION_APPROVAL" and re.search(
        r"(?m)^\s*\|\s*Last completed stage\s*\|\s*INPUT_READY\s*\|", text
    )
    if not preserve_provisional:
        text = _replace_state_field(
            text, "Last completed stage", LAST_COMPLETED_STAGE.get(stage, stage)
        )
    text = _replace_state_field(text, "Next action", NEXT_ACTION[stage])
    text = _refresh_state_snapshot(text, run_path, stage)
    state_path.write_text(text, encoding="utf-8")
    return inspect_run(run_path)


def inspect_run(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    stage = read_current_stage(run_path)
    artifact_status: dict[str, bool] = {}
    milestone = {
        "WAITING_FOR_R0": "EXPERIMENT_DESIGN_READY",
        "R0_PASSED": "EXPERIMENT_DESIGN_READY",
        "R0_FAILED_RETURN_TO_DESIGN": "EXPERIMENT_DESIGN_READY",
        "WAITING_FOR_METHOD_REVISION_APPROVAL": "EXPERIMENT_DESIGN_READY",
        "EXECUTION_IN_PROGRESS": "IMPLEMENTATION_READY",
        "IDEA_ABANDONED": "EXPERIMENT_DESIGN_READY",
    }.get(stage, stage)
    for required_stage in STAGE_ORDER[: STAGE_ORDER.index(milestone) + 1]:
        for relative in STAGE_REQUIREMENTS[required_stage]:
            artifact_status[relative] = (run_path / relative).exists()
    for relative in {
        "WAITING_FOR_R0": ("r0_plan.md",),
        "R0_PASSED": ("r0_record.json",),
        "R0_FAILED_RETURN_TO_DESIGN": ("r0_record.json",),
        "WAITING_FOR_METHOD_REVISION_APPROVAL": (
            "breakpoint_recovery.md",
            "method_revision_request.md",
            "method_revision_proposal.md",
        ),
        "IDEA_ABANDONED": (
            "breakpoint_recovery.md",
            "method_revision_request.md",
            "method_revision_proposal.md",
            "method_revision_decision.md",
            "idea_abandonment.md",
        ),
    }.get(stage, ()):
        artifact_status[relative] = (run_path / relative).exists()
    missing = sorted(path for path, exists in artifact_status.items() if not exists)
    return {
        "status": "PASS" if not missing else "INCOMPLETE",
        "validation_scope": "ARTIFACT_COMPLETENESS",
        "run_dir": str(run_path.resolve()),
        "current_stage": stage,
        "next_action": NEXT_ACTION[stage],
        "artifacts": artifact_status,
        "missing_artifacts": missing,
    }


def advance_run(
    run_dir: str | Path,
    stage: str,
    *,
    changed_input: str,
    literal_result: str,
) -> dict[str, Any]:
    """Advance the human-readable state after target-stage artifacts exist."""

    if stage not in KNOWN_STAGES:
        raise ValueError(f"Unknown prompt-driven stage: {stage}")
    run_path = Path(run_dir)
    current = read_current_stage(run_path)
    provisional_revision = stage == "WAITING_FOR_METHOD_REVISION_APPROVAL" and (
        current == "R0_FAILED_RETURN_TO_DESIGN" or (
            current == "WAITING_FOR_METHOD_REVISION_APPROVAL" and re.search(
                r"(?m)^\s*\|\s*Last completed stage\s*\|\s*INPUT_READY\s*\|",
                (run_path / "AUTODESIGN_STATE.md").read_text(encoding="utf-8"),
            )
        )
    )
    if provisional_revision:
        for name in ("experiment_design.md", "r0_record.json", "breakpoint_recovery.md", "method_revision_request.md", "method_revision_proposal.md"):
            if not (run_path / name).is_file():
                raise ValueError("Provisional revision requires " + name)
        if not REVISION_ID_PATTERN.search((run_path / "method_revision_proposal.md").read_text(encoding="utf-8")):
            raise ValueError("Provisional revision requires explicit Revision ID")
    if stage == "WAITING_FOR_METHOD_REVISION_APPROVAL" and current not in {
        "EXPERIMENT_DESIGN_READY",
        "IMPLEMENTATION_READY",
        "EXECUTION_IN_PROGRESS",
        "R0_FAILED_RETURN_TO_DESIGN",
        "WAITING_FOR_METHOD_REVISION_APPROVAL",
    }:
        raise ValueError(
            "WAITING_FOR_METHOD_REVISION_APPROVAL requires an accepted design or active run"
        )
    if stage == "EXPERIMENT_DESIGN_READY" and current == ("WAITING_FOR_METHOD_REVISION_APPROVAL"):
        _, decision = _method_revision_decision(run_path)
        if decision not in {
            "APPROVE_MINIMAL_METHOD_REVISION",
            "APPROVE_EXCEPTION_METHOD_REVISION",
        }:
            raise ValueError(
                "EXPERIMENT_DESIGN_READY requires literal human approval for the matching "
                f"method revision; got {decision}"
            )
    if stage == "IDEA_ABANDONED":
        if current != "WAITING_FOR_METHOD_REVISION_APPROVAL":
            raise ValueError(
                "IDEA_ABANDONED requires current stage WAITING_FOR_METHOD_REVISION_APPROVAL"
            )
        _, decision = _method_revision_decision(run_path)
        if decision != "ABANDON_IDEA":
            raise ValueError(
                "IDEA_ABANDONED requires literal Decision: ABANDON_IDEA for the matching revision"
            )
    if stage in {"EXPERIMENT_DESIGN_READY", "WAITING_FOR_R0"}:
        design_check = check_design(run_path)
        if design_check.get("status") != "PASS":
            raise ValueError(
                f"{stage} requires a structurally valid design: "
                + "; ".join(str(item) for item in design_check.get("errors", []))
            )
        declared = design_check.get("declared_design_readiness")
        required = {
            "EXPERIMENT_DESIGN_READY": "PASS",
            "WAITING_FOR_R0": "PROVISIONAL_WAITING_FOR_R0",
        }[stage]
        if declared != required:
            raise ValueError(
                f"{stage} requires coverage-audit Verdict: {required}; got {declared!r}"
            )
    if stage == "RESULT_DIAGNOSIS_READY":
        summary_path = run_path / "result_summary.json"
        if not summary_path.is_file():
            raise ValueError("RESULT_DIAGNOSIS_READY requires result_summary.json from ingest")
        summary = read_json(summary_path)
        summary_status = summary.get("status") if isinstance(summary, dict) else None
        if summary_status != "READY_FOR_GPT_DIAGNOSIS":
            raise ValueError(
                "RESULT_DIAGNOSIS_READY requires result_summary.json status "
                f"READY_FOR_GPT_DIAGNOSIS; got {summary_status!r}"
            )
    if stage == "COMPLETE" and current != "INTEGRITY_AUDIT_PASS":
        raise ValueError("COMPLETE requires current stage INTEGRITY_AUDIT_PASS")
    if stage in {"INTEGRITY_AUDIT_PASS", "COMPLETE"} and _audit_verdict(run_path) != "PASS":
        raise ValueError(f"{stage} requires integrity_audit.md with literal Verdict: PASS")
    state_path = run_path / "AUTODESIGN_STATE.md"
    text = state_path.read_text(encoding="utf-8")
    original_text = text
    text = _replace_state_field(text, "Current stage", stage)
    if not provisional_revision:
        text = _replace_state_field(
            text, "Last completed stage", LAST_COMPLETED_STAGE.get(stage, stage)
        )
    text = _replace_state_field(text, "Next action", NEXT_ACTION[stage])
    text = _refresh_state_snapshot(text, run_path, stage)
    history_rows = re.findall(r"^\s*\|\s*(\d+)\s*\|", text, flags=re.MULTILINE)
    round_index = max((int(value) for value in history_rows), default=0) + 1
    next_action = (
        "pipeline complete"
        if stage == "COMPLETE"
        else "idea abandoned"
        if stage == "IDEA_ABANDONED"
        else f"run {NEXT_ACTION[stage]}"
    )
    text = text.rstrip() + (
        f"\n| {round_index} | {current} | {stage} | "
        f"{_markdown_table_cell(changed_input)} | "
        f"{_markdown_table_cell(literal_result)} | {next_action} |\n"
    )
    state_path.write_text(text, encoding="utf-8")
    report = inspect_run(run_path)
    if report["missing_artifacts"]:
        state_path.write_text(original_text, encoding="utf-8")
        raise ValueError(
            "Cannot accept stage with missing artifacts: " + ", ".join(report["missing_artifacts"])
        )
    return report
