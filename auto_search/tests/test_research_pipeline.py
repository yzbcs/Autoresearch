from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import research_pipeline


def paper(paper_id: str) -> dict[str, object]:
    return {
        "id": paper_id,
        "title": f"Paper {paper_id}",
        "authors": "A. Author",
        "year": 2025,
        "venue": "Venue",
        "scholar_url": "https://scholar.google.com/",
        "source_url": "https://example.com/paper",
        "source_scope": "Abstract",
        "reported_weakness": "Small features are lost.",
        "evidence": ["The abstract reports feature loss."],
        "evidence_status": "directly_reported",
        "source_method_summary": "The source adds a standard feature pyramid.",
        "inference_constraints": "Use only the input image and text query at inference time.",
        "benchmark_candidates": [
            {
                "name": "Public Test Benchmark",
                "public_url": "https://example.com/benchmark",
                "released_labels": "Released image labels and masks.",
                "supported_evaluation": "Task score and mechanism-level retention score.",
                "allowed_adaptation": "Deterministic size strata from released masks.",
            }
        ],
    }


def evaluation(ids: list[str]) -> dict[str, object]:
    items = []
    for paper_id in ids:
        items.append(
            {
                "paper_id": paper_id,
                "idea_title": f"Idea {paper_id}",
                "verdict": "promising",
                "scores": {
                    key: (5 if key == "annotation_compliance" else 4)
                    for key in research_pipeline.SCORE_KEYS
                },
                "strengths": ["Specific mechanism."],
                "major_risks": ["Overlap risk."],
                "required_revisions": ["Add a stronger control."],
                "rejection_reason": "Novelty is not yet established.",
                "literature_overlap_risk": "Memory and token-selection methods.",
            }
        )
    return {
        "evaluations": items,
        "ranking": ids,
        "portfolio_assessment": "The portfolio is testable.",
    }


class ResearchPipelineTests(unittest.TestCase):
    def test_load_manifest_accepts_one_directly_relevant_paper(self) -> None:
        manifest = {"search": {}, "papers": [paper("a")]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "papers.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded = research_pipeline.load_manifest(path)
        self.assertEqual([item["id"] for item in loaded["papers"]], ["a"])

    def test_load_manifest_requires_reason_for_blocked_feasibility(self) -> None:
        blocked = paper("a")
        blocked["feasibility_status"] = "blocked"
        manifest = {"search": {}, "papers": [blocked, paper("b")]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "papers.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "feasibility_blocker"):
                research_pipeline.load_manifest(path)

    def test_weakness_document_preserves_source_links(self) -> None:
        document = research_pipeline.weakness_document(paper("a"))
        self.assertIn("Google Scholar", document)
        self.assertIn("https://example.com/paper", document)
        self.assertIn("Small features are lost.", document)
        self.assertIn("Source Method to Avoid Reproducing", document)
        self.assertIn("Public Benchmark Candidates", document)
        self.assertIn("Public Test Benchmark", document)

    def test_w2c_input_excludes_source_method_and_preserves_constraints(self) -> None:
        rendered = research_pipeline.w2c_input(paper("a"))
        self.assertIn("must not be reproduced", rendered)
        self.assertIn("standard feature pyramid", rendered)
        self.assertIn("input image and text query", rendered)
        self.assertIn("Verified public benchmark candidates", rendered)
        self.assertIn("Do not request new doctor annotation", rendered)

    def test_w2c_input_makes_verified_blocker_explicit(self) -> None:
        blocked = paper("a")
        blocked["feasibility_status"] = "blocked"
        blocked["feasibility_blocker"] = "Required label mapping is not verified."
        rendered = research_pipeline.w2c_input(blocked)
        self.assertIn("Verified feasibility status: blocked", rendered)
        self.assertIn("return PASS now", rendered)

    def test_generate_portfolio_rejects_idea_for_blocked_paper(self) -> None:
        blocked = paper("a")
        blocked["feasibility_status"] = "blocked"
        blocked["feasibility_blocker"] = "Required label mapping is not verified."
        manifest = {"search": {}, "papers": [blocked]}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(research_pipeline.generate_idea, "run_codex", return_value="# Idea: invalid\n"):
                with self.assertRaisesRegex(ValueError, "must produce PASS"):
                    research_pipeline.generate_portfolio(
                        manifest,
                        Path(directory),
                        model=None,
                        timeout=30,
                        force=True,
                    )

    def test_evaluation_prompt_contains_every_idea(self) -> None:
        portfolio = [
            {"paper": paper("a"), "idea_markdown": "# Idea A"},
            {"paper": paper("b"), "idea_markdown": "# Idea B"},
        ]
        prompt = research_pipeline.render_evaluation_prompt(portfolio)
        self.assertIn("# Idea A", prompt)
        self.assertIn("# Idea B", prompt)
        self.assertNotIn("{{PORTFOLIO_JSON}}", prompt)

    def test_validate_evaluation_requires_complete_ranking(self) -> None:
        response = evaluation(["a", "b"])
        research_pipeline.validate_evaluation(response, ["a", "b"])
        response["ranking"] = ["a"]
        with self.assertRaisesRegex(ValueError, "permutation"):
            research_pipeline.validate_evaluation(response, ["a", "b"])

    def test_validate_evaluation_enforces_novelty_gate(self) -> None:
        response = evaluation(["a", "b"])
        response["evaluations"][0]["scores"]["novelty_plausibility"] = 2
        with self.assertRaisesRegex(ValueError, "Novelty gate"):
            research_pipeline.validate_evaluation(response, ["a", "b"])

    def test_validate_evaluation_enforces_benchmark_gate(self) -> None:
        response = evaluation(["a", "b"])
        response["evaluations"][0]["scores"]["benchmark_readiness"] = 2
        with self.assertRaisesRegex(ValueError, "Feasibility gate"):
            research_pipeline.validate_evaluation(response, ["a", "b"])

    def test_validate_evaluation_enforces_no_new_doctor_annotation(self) -> None:
        response = evaluation(["a", "b"])
        response["evaluations"][0]["scores"]["annotation_compliance"] = 1
        with self.assertRaisesRegex(ValueError, "Feasibility gate"):
            research_pipeline.validate_evaluation(response, ["a", "b"])

    def test_validate_evaluation_accepts_pass_document_and_ranks_it_last(self) -> None:
        response = evaluation(["a", "b"])
        response["evaluations"][1]["verdict"] = "pass"
        response["evaluations"][1]["scores"]["benchmark_readiness"] = 1
        research_pipeline.validate_evaluation(response, ["a", "b"], {"b"})

        response["ranking"] = ["b", "a"]
        with self.assertRaisesRegex(ValueError, "ranked after"):
            research_pipeline.validate_evaluation(response, ["a", "b"], {"b"})

    def test_render_evaluation_markdown_includes_scores_and_risks(self) -> None:
        response = evaluation(["a", "b"])
        rendered = research_pipeline.render_evaluation_markdown(
            response,
            [paper("a"), paper("b")],
        )
        self.assertIn("4.08/5", rendered)
        self.assertIn("innovation-weighted", rendered)
        self.assertIn("Skeptical rejection case", rendered)
        self.assertIn("Literature-overlap risk", rendered)


if __name__ == "__main__":
    unittest.main()
