from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tempfile
from threading import Event
from typing import Any, Callable

import generate_idea


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "sources" / "papers.json"
DEFAULT_RUN_DIR = ROOT / "research_runs" / "scholar-small-lesion"
EVALUATION_PROMPT_PATH = ROOT / "evaluation_prompt.md"
EVALUATION_SCHEMA_PATH = ROOT / "schemas" / "evaluation.schema.json"
SCORE_KEYS = (
    "problem_grounding",
    "root_cause_quality",
    "point_to_point_alignment",
    "terminology_discipline",
    "novelty_plausibility",
    "implementation_feasibility",
    "benchmark_readiness",
    "resource_feasibility",
    "annotation_compliance",
    "validation_strength",
    "contribution_clarity",
)
SCORE_WEIGHTS = {key: (3 if key == "novelty_plausibility" else 1) for key in SCORE_KEYS}


def weighted_score(scores: dict[str, int]) -> float:
    total_weight = sum(SCORE_WEIGHTS.values())
    return sum(scores[key] * SCORE_WEIGHTS[key] for key in SCORE_KEYS) / total_weight


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("search"), dict):
        raise ValueError("Manifest must contain a search object.")
    papers = manifest.get("papers")
    if not isinstance(papers, list) or not papers:
        raise ValueError("Manifest must contain at least one paper.")
    ids: list[str] = []
    required = {
        "id",
        "title",
        "authors",
        "year",
        "venue",
        "scholar_url",
        "source_url",
        "source_scope",
        "reported_weakness",
        "evidence",
        "evidence_status",
    }
    for paper in papers:
        if not isinstance(paper, dict) or not required <= set(paper):
            raise ValueError(f"Paper record is missing fields: {paper!r}")
        if not isinstance(paper["id"], str) or not re.fullmatch(r"[a-z0-9_]+", paper["id"]):
            raise ValueError(f"Invalid paper id: {paper.get('id')!r}")
        if not isinstance(paper["reported_weakness"], str) or not paper["reported_weakness"].strip():
            raise ValueError(f"Missing weakness for {paper['id']}")
        if not isinstance(paper["evidence"], list) or not paper["evidence"]:
            raise ValueError(f"Missing evidence for {paper['id']}")
        benchmark_candidates = paper.get("benchmark_candidates")
        if benchmark_candidates is not None:
            if not isinstance(benchmark_candidates, list) or not benchmark_candidates:
                raise ValueError(f"Invalid benchmark candidates for {paper['id']}")
            for candidate in benchmark_candidates:
                required_benchmark_fields = {
                    "name",
                    "public_url",
                    "released_labels",
                    "supported_evaluation",
                    "allowed_adaptation",
                }
                if not isinstance(candidate, dict) or not required_benchmark_fields <= set(candidate):
                    raise ValueError(f"Invalid benchmark candidate for {paper['id']}: {candidate!r}")
        feasibility_status = paper.get("feasibility_status", "unknown")
        if feasibility_status not in {"ready", "blocked", "unknown"}:
            raise ValueError(f"Invalid feasibility status for {paper['id']}: {feasibility_status!r}")
        if feasibility_status == "blocked" and not str(paper.get("feasibility_blocker", "")).strip():
            raise ValueError(f"Blocked paper requires a feasibility_blocker: {paper['id']}")
        ids.append(paper["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Paper ids must be unique.")
    return manifest


def write_json_atomic(path: Path, value: Any, force: bool = True) -> None:
    generate_idea.write_text_atomic(
        path,
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        force=force,
    )


def weakness_document(paper: dict[str, Any]) -> str:
    evidence = "\n".join(f"- {item}" for item in paper["evidence"])
    source_method = paper.get("source_method_summary")
    source_method_section = (
        f"\n## Source Method to Avoid Reproducing\n\n{source_method}\n"
        if isinstance(source_method, str) and source_method.strip()
        else ""
    )
    benchmark_candidates = paper.get("benchmark_candidates", [])
    benchmark_section = ""
    if benchmark_candidates:
        benchmark_lines = []
        for candidate in benchmark_candidates:
            benchmark_lines.append(
                f"- {candidate['name']}: {candidate['public_url']} | "
                f"task type: {candidate.get('task_type', 'not specified')} | "
                f"usage mode: {candidate.get('usage_mode', 'not specified')} | "
                f"released labels: {candidate['released_labels']} | "
                f"supported evaluation: {candidate['supported_evaluation']} | "
                f"allowed adaptation: {candidate['allowed_adaptation']}"
            )
        benchmark_section = "\n## Public Benchmark Candidates\n\n" + "\n".join(benchmark_lines) + "\n"
    return (
        f"# {paper['title']}\n\n"
        f"- Authors: {paper['authors']}\n"
        f"- Venue: {paper['venue']} ({paper['year']})\n"
        f"- Google Scholar: {paper['scholar_url']}\n"
        f"- Verified source: {paper['source_url']}\n"
        f"- Evidence scope: {paper['source_scope']}\n"
        f"- Evidence status: {paper['evidence_status']}\n\n"
        "## Weakness\n\n"
        f"{paper['reported_weakness']}\n\n"
        "## Source Evidence\n\n"
        f"{evidence}\n"
        f"{source_method_section}"
        f"{benchmark_section}"
    )


def w2c_input(paper: dict[str, Any]) -> str:
    evidence = " ".join(paper["evidence"])
    domain = paper.get("domain", "medical image analysis and medical vision-language modeling")
    source_method = paper.get("source_method_summary", "Not supplied; infer no details beyond the evidence notes.")
    inference_constraints = paper.get(
        "inference_constraints",
        "Do not assume lesion-location annotations or other privileged annotations at inference time.",
    )
    benchmark_candidates = paper.get("benchmark_candidates")
    benchmark_evidence = (
        json.dumps(benchmark_candidates, ensure_ascii=False)
        if benchmark_candidates
        else "Not supplied. Return PASS unless a named public benchmark and released labels can be stated confidently without fabrication."
    )
    feasibility_status = paper.get("feasibility_status", "unknown")
    feasibility_blocker = paper.get("feasibility_blocker", "None supplied.")
    return (
        f"Research domain: {domain}. "
        "The following weakness was extracted from a verified primary paper source. "
        "Propose a mechanism-level solution rather than a stack of familiar modules. "
        f"Source paper: {paper['title']} ({paper['year']}). "
        f"Reported weakness: {paper['reported_weakness']} "
        f"Evidence notes: {evidence} "
        f"Source method or tested remedy that must not be reproduced: {source_method} "
        f"Inference constraints: {inference_constraints} "
        f"Verified public benchmark candidates: {benchmark_evidence} "
        f"Verified feasibility status: {feasibility_status}. "
        f"Verified feasibility blocker: {feasibility_blocker} "
        "When the verified feasibility status is blocked, return PASS now and do not infer or assume a missing label, mapping, split, permission, or protocol. "
        "Use only released annotations. Do not request new doctor annotation, review, rating, adjudication, or expert evaluation."
    )


def generate_portfolio(
    manifest: dict[str, Any],
    run_dir: Path,
    model: str | None,
    timeout: int,
    force: bool,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
    cancel_event: Event | None = None,
    process_callback: Callable[[Any | None], None] | None = None,
) -> list[dict[str, Any]]:
    portfolio: list[dict[str, Any]] = []
    for paper in manifest["papers"]:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("调研已停止，已完成产物保留。")
        paper_dir = run_dir / "papers" / paper["id"]
        idea_path = paper_dir / "idea.md"
        prompt_path = paper_dir / "prompt.md"
        weakness_path = paper_dir / "weakness.md"
        source_path = paper_dir / "source.json"

        should_generate = force or not idea_path.is_file()
        if not should_generate:
            idea = idea_path.read_text(encoding="utf-8")
            try:
                generate_idea.validate_markdown(idea)
            except ValueError as error:
                print(f"stale idea: {paper['id']} ({error}); regenerating", flush=True)
                should_generate = True
        if should_generate:
            prompt = generate_idea.render_prompt(w2c_input(paper), "zh")
            idea = generate_idea.run_codex(
                prompt,
                model=model,
                timeout=timeout,
                cancel_event=cancel_event,
                process_callback=process_callback,
                workspace=run_dir,
            )
            if paper.get("feasibility_status") == "blocked" and not generate_idea.is_pass_markdown(idea):
                raise ValueError(
                    f"Feasibility-blocked paper must produce PASS: {paper['id']}"
                )
            generate_idea.write_text_atomic(idea_path, idea, force=True)
            generate_idea.write_text_atomic(prompt_path, prompt, force=True)

        generate_idea.write_text_atomic(
            weakness_path,
            weakness_document(paper),
            force=True,
        )
        write_json_atomic(source_path, paper)
        portfolio.append({"paper": paper, "idea_markdown": idea})
        print(f"generated: {paper['id']} -> {idea_path}", flush=True)
        if progress_callback is not None:
            progress_callback(len(portfolio), len(manifest["papers"]), paper)
    return portfolio


def load_portfolio(manifest: dict[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    portfolio: list[dict[str, Any]] = []
    for paper in manifest["papers"]:
        idea_path = run_dir / "papers" / paper["id"] / "idea.md"
        if not idea_path.is_file():
            raise FileNotFoundError(f"Idea not found; run generate first: {idea_path}")
        idea = idea_path.read_text(encoding="utf-8")
        generate_idea.validate_markdown(idea)
        portfolio.append({"paper": paper, "idea_markdown": idea})
    return portfolio


def render_evaluation_prompt(portfolio: list[dict[str, Any]]) -> str:
    template = EVALUATION_PROMPT_PATH.read_text(encoding="utf-8")
    placeholder = "{{PORTFOLIO_JSON}}"
    if template.count(placeholder) != 1:
        raise ValueError("Evaluation prompt placeholder must appear exactly once.")
    payload = json.dumps(portfolio, ensure_ascii=False, indent=2)
    return template.replace(placeholder, payload).strip() + "\n"


def execute_json_agent(
    prompt: str,
    schema_path: Path,
    model: str | None,
    timeout: int,
    cancel_event: Event | None = None,
    process_callback: Callable[[Any | None], None] | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    workspace = (workspace or Path.cwd()).resolve()
    prompt = generate_idea.with_recovery_context(prompt, workspace)
    codex_cli = generate_idea.resolve_codex_cli()
    with tempfile.TemporaryDirectory(prefix="w2c-eval-") as temporary_dir:
        raw_output = Path(temporary_dir) / "evaluation.json"
        command = generate_idea.build_codex_command(codex_cli, raw_output, model, workspace)
        command[-1:-1] = ["--output-schema", str(schema_path)]
        result = generate_idea.run_command(
            command,
            prompt,
            timeout,
            cancel_event=cancel_event,
            process_callback=process_callback,
            cwd=workspace,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Codex evaluator failed.\n"
                f"stdout:\n{result.stdout[-3000:]}\n"
                f"stderr:\n{result.stderr[-3000:]}"
            )
        if not raw_output.is_file():
            raise RuntimeError("Codex evaluator did not write its final response.")
        response = json.loads(raw_output.read_text(encoding="utf-8"))
    if not isinstance(response, dict):
        raise ValueError("Evaluator response must be a JSON object.")
    return response


def validate_evaluation(
    response: dict[str, Any],
    expected_ids: list[str],
    pass_document_ids: set[str] | None = None,
) -> None:
    pass_document_ids = pass_document_ids or set()
    evaluations = response.get("evaluations")
    ranking = response.get("ranking")
    if not isinstance(evaluations, list):
        raise ValueError("Evaluations must be a list.")
    ids = [item.get("paper_id") for item in evaluations if isinstance(item, dict)]
    if len(ids) != len(evaluations) or set(ids) != set(expected_ids) or len(ids) != len(set(ids)):
        raise ValueError("Evaluator must return exactly one evaluation per paper id.")
    if not isinstance(ranking, list) or ranking != list(dict.fromkeys(ranking)):
        raise ValueError("Ranking must contain unique paper ids.")
    if set(ranking) != set(expected_ids) or len(ranking) != len(expected_ids):
        raise ValueError("Ranking must be a permutation of all paper ids.")
    evaluation_map = {item["paper_id"]: item for item in evaluations}
    seen_pass = False
    for paper_id in ranking:
        is_pass_verdict = evaluation_map[paper_id].get("verdict") == "pass"
        if seen_pass and not is_pass_verdict:
            raise ValueError("PASS verdicts must be ranked after all non-PASS proposals.")
        seen_pass = seen_pass or is_pass_verdict
    for evaluation in evaluations:
        scores = evaluation.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(SCORE_KEYS):
            raise ValueError(f"Invalid score dimensions for {evaluation.get('paper_id')}")
        if any(not isinstance(scores[key], int) or not 1 <= scores[key] <= 5 for key in SCORE_KEYS):
            raise ValueError(f"Scores must be integers from 1 to 5 for {evaluation.get('paper_id')}")
        novelty = scores["novelty_plausibility"]
        verdict = evaluation.get("verdict")
        paper_id = evaluation.get("paper_id")
        if paper_id in pass_document_ids and verdict != "pass":
            raise ValueError(f"PASS document requires a pass verdict for {paper_id}")
        feasibility_failed = (
            scores["benchmark_readiness"] <= 2
            or scores["resource_feasibility"] <= 2
            or scores["annotation_compliance"] != 5
        )
        if feasibility_failed and verdict != "pass":
            raise ValueError(f"Feasibility gate requires a pass verdict for {paper_id}")
        if novelty <= 2 and not feasibility_failed and verdict != "weak":
            raise ValueError(
                f"Novelty gate requires a weak verdict for {paper_id}"
            )
        if verdict == "promising" and novelty < 3:
            raise ValueError(
                f"Promising verdict requires novelty of at least 3 for {evaluation.get('paper_id')}"
            )
        if verdict == "strong":
            non_novelty_scores = [scores[key] for key in SCORE_KEYS if key != "novelty_plausibility"]
            if novelty < 4 or min(non_novelty_scores) < 4 or scores["annotation_compliance"] != 5:
                raise ValueError(
                    f"Strong verdict does not satisfy the innovation gate for {paper_id}"
                )


def render_evaluation_markdown(
    response: dict[str, Any],
    papers: list[dict[str, Any]],
) -> str:
    paper_map = {paper["id"]: paper for paper in papers}
    evaluation_map = {item["paper_id"]: item for item in response["evaluations"]}
    lines = ["# Codex Evaluation", "", response["portfolio_assessment"], "", "## Ranking", ""]
    for rank, paper_id in enumerate(response["ranking"], start=1):
        item = evaluation_map[paper_id]
        average = weighted_score(item["scores"])
        lines.append(
            f"{rank}. **{paper_map[paper_id]['title']}** — {item['verdict']} — {average:.2f}/5 innovation-weighted"
        )
    for paper_id in response["ranking"]:
        item = evaluation_map[paper_id]
        paper = paper_map[paper_id]
        lines.extend(["", f"## {paper['title']}", "", f"- Verdict: `{item['verdict']}`"])
        for key in SCORE_KEYS:
            lines.append(f"- {key}: {item['scores'][key]}/5")
        lines.extend(["", "### Strengths", ""])
        lines.extend(f"- {value}" for value in item["strengths"])
        lines.extend(["", "### Major Risks", ""])
        lines.extend(f"- {value}" for value in item["major_risks"])
        lines.extend(["", "### Required Revisions", ""])
        lines.extend(f"- {value}" for value in item["required_revisions"])
        lines.extend(
            [
                "",
                f"**Skeptical rejection case:** {item['rejection_reason']}",
                "",
                f"**Literature-overlap risk:** {item['literature_overlap_risk']}",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def evaluate_portfolio(
    portfolio: list[dict[str, Any]],
    run_dir: Path,
    model: str | None,
    timeout: int,
    force: bool,
    cancel_event: Event | None = None,
    process_callback: Callable[[Any | None], None] | None = None,
) -> dict[str, Any]:
    json_path = run_dir / "evaluation.json"
    markdown_path = run_dir / "evaluation.md"
    prompt_path = run_dir / "evaluation.prompt.md"
    expected_ids = [entry["paper"]["id"] for entry in portfolio]
    pass_document_ids = {
        entry["paper"]["id"]
        for entry in portfolio
        if generate_idea.is_pass_markdown(entry["idea_markdown"])
    }
    repair_context = ""
    should_evaluate = force or not json_path.is_file()
    if not should_evaluate:
        try:
            response = json.loads(json_path.read_text(encoding="utf-8"))
            validate_evaluation(response, expected_ids, pass_document_ids)
        except ValueError as error:
            print(f"stale evaluation ({error}); reevaluating", flush=True)
            repair_context = f"\nPrevious invalid output:\n{json_path.read_text(encoding='utf-8')}\nValidation error: {error}\n"
            should_evaluate = True
    if should_evaluate:
        schema = json.loads(EVALUATION_SCHEMA_PATH.read_text(encoding="utf-8"))
        schema["properties"]["ranking"]["items"]["enum"] = expected_ids
        schema["properties"]["evaluations"]["items"]["properties"]["paper_id"]["enum"] = expected_ids
        schema_path = run_dir / "evaluation.schema.json"
        write_json_atomic(schema_path, schema)
        base_prompt = render_evaluation_prompt(portfolio)
        for attempt in range(3):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Evaluation cancelled.")
            prompt = (base_prompt + repair_context
                      + "\nAllowed paper IDs (use exactly, each once in ranking): "
                      + json.dumps(expected_ids, ensure_ascii=False)
                      + "\nCorrect any validation errors and return the complete evaluation JSON.\n")
            generate_idea.write_text_atomic(prompt_path, prompt, force=True)
            response = None
            try:
                response = execute_json_agent(
                    prompt, schema_path, model, timeout,
                    cancel_event=cancel_event, process_callback=process_callback,
                    workspace=run_dir,
                )
                validate_evaluation(response, expected_ids, pass_document_ids)
            except ValueError as error:
                invalid = response
                with (run_dir / "evaluation.repair.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"attempt": attempt + 1, "error": str(error),
                                          "response": invalid}, ensure_ascii=False) + "\n")
                if attempt == 2:
                    raise ValueError(f"Evaluation invalid after 3 attempts: {error}") from error
                repair_context = ("\nPrevious invalid output:\n" + json.dumps(invalid, ensure_ascii=False)
                                  + f"\nValidation error: {error}\n")
                print(f"evaluation validation failed; repairing ({attempt + 1}/2): {error}", flush=True)
            else:
                break
        write_json_atomic(json_path, response)
    validate_evaluation(response, expected_ids, pass_document_ids)
    markdown = render_evaluation_markdown(
        response,
        [entry["paper"] for entry in portfolio],
    )
    generate_idea.write_text_atomic(markdown_path, markdown, force=True)
    print(f"evaluated: {markdown_path}", flush=True)
    return response


def build_index(manifest: dict[str, Any], run_dir: Path) -> None:
    lines = [
        "# Scholar Weakness-to-Contribution Portfolio",
        "",
        f"- Search engine: {manifest['search']['engine']}",
        f"- Query: `{manifest['search']['query']}`",
        f"- Search date: {manifest['search']['searched_at']}",
        f"- [Search results]({manifest['search']['query_url']})",
        "",
    ]
    if (run_dir / "IDEAS.md").is_file():
        lines.extend(["- [10 个 Medical VLM Idea 总索引](IDEAS.md)", ""])
    lines.extend(["## Papers and Artifacts", ""])
    for paper in manifest["papers"]:
        base = Path("papers") / paper["id"]
        lines.extend(
            [
                f"### {paper['title']}",
                "",
                f"- [Google Scholar]({paper['scholar_url']})",
                f"- [Verified source]({paper['source_url']})",
                f"- [Weakness]({(base / 'weakness.md').as_posix()})",
                f"- [Idea or PASS feasibility decision]({(base / 'idea.md').as_posix()})",
                "",
            ]
        )
    if (run_dir / "evaluation.md").is_file():
        lines.extend(["## Independent Evaluation", "", "- [Codex evaluation](evaluation.md)", ""])
    generate_idea.write_text_atomic(run_dir / "README.md", "\n".join(lines), force=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and independently evaluate W2C ideas from a paper manifest."
    )
    parser.add_argument("stage", choices=("generate", "evaluate", "all"), nargs="?", default="all")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--model", help="Optional Codex model override for generation and evaluation.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero.")
    manifest = load_manifest(args.manifest.resolve())
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(run_dir / "manifest.snapshot.json", manifest)

    if args.stage in {"generate", "all"}:
        portfolio = generate_portfolio(
            manifest,
            run_dir,
            model=args.model,
            timeout=args.timeout,
            force=args.force,
        )
    else:
        portfolio = load_portfolio(manifest, run_dir)
    if args.stage in {"evaluate", "all"}:
        evaluate_portfolio(
            portfolio,
            run_dir,
            model=args.model,
            timeout=args.timeout,
            force=args.force,
        )
    build_index(manifest, run_dir)
    print(run_dir / "README.md")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
