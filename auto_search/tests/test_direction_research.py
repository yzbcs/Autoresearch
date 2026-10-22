import json
import unittest
from unittest import mock

import direction_research


def paper_record(title: str, year: int = 2025):
    return {
        "title": title,
        "authors": "A. Researcher et al.",
        "year": year,
        "venue": "CVPR",
        "domain": "Medical vision-language modeling",
        "source_url": "https://example.org/paper",
        "source_scope": "Paper experiments and official repository",
        "reported_weakness": "模型在细粒度目标上出现明显漏检。",
        "evidence": ["论文报告细粒度子集性能下降。", "官方数据发布了任务标签。"],
        "evidence_status": "directly_reported",
        "source_method_summary": "论文使用普通视觉指令微调。",
        "inference_constraints": "推理时只使用图像和问题。",
        "benchmark_candidates": [
            {
                "name": f"PublicBench {index}",
                "public_url": f"https://example.org/benchmark-{index}",
                "task_type": "细粒度分类",
                "usage_mode": "direct",
                "released_labels": "类别与区域标签",
                "supported_evaluation": "分类准确率与定位召回率",
                "allowed_adaptation": "直接使用原协议",
            }
            for index in range(1, 4)
        ],
        "feasibility_status": "ready",
        "feasibility_blocker": "",
    }


class DirectionResearchTests(unittest.TestCase):
    def test_output_schema_avoids_unsupported_all_of(self):
        schema = json.loads(direction_research.SCHEMA_PATH.read_text(encoding="utf-8"))

        def contains_all_of(value):
            if isinstance(value, dict):
                return "allOf" in value or any(contains_all_of(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_all_of(item) for item in value)
            return False

        self.assertFalse(contains_all_of(schema))

    def test_prompt_handles_broad_direction_and_requires_live_search(self):
        prompt = direction_research.render_research_prompt("医学图像", 3)
        self.assertIn("Live web search is enabled", prompt)
        self.assertIn("up to 3", prompt)
        self.assertIn('"医学图像"', prompt)
        self.assertIn("Simplified Chinese", prompt)
        self.assertIn("binding constraints", prompt)
        self.assertIn("never fill the requested count with adjacent work", prompt)
        self.assertIn("fewer than three is not by itself a blocker", prompt)

    def test_build_manifest_enriches_papers_and_creates_unique_ids(self):
        response = {
            "scope_summary": "聚焦细粒度医学视觉问答。",
            "papers": [paper_record("A Fine-grained Study"), paper_record("A Fine-grained Study")],
        }
        manifest = direction_research.build_manifest("细粒度医学视觉问答", response, 2)
        self.assertEqual(len(manifest["papers"]), 2)
        self.assertNotEqual(manifest["papers"][0]["id"], manifest["papers"][1]["id"])
        self.assertTrue(manifest["papers"][0]["scholar_url"].startswith("https://scholar.google.com/"))
        self.assertEqual(manifest["search"]["scope_summary"], "聚焦细粒度医学视觉问答。")

    def test_ready_paper_requires_a_verified_core_task_benchmark(self):
        paper = paper_record("No Benchmark")
        paper["benchmark_candidates"] = []
        response = {"scope_summary": "test", "papers": [paper, paper_record("Second Paper")]}
        with self.assertRaisesRegex(ValueError, "no verified core-task benchmark"):
            direction_research.build_manifest("方向", response, 2)

    def test_manifest_may_return_fewer_directly_relevant_papers_than_requested(self):
        response = {"scope_summary": "只找到一篇直接相关论文。", "papers": [paper_record("Direct Paper")]}
        manifest = direction_research.build_manifest("严格方向", response, 3)
        self.assertEqual(len(manifest["papers"]), 1)

    def test_blocked_paper_can_omit_benchmark_after_normalization(self):
        blocked = paper_record("Blocked Paper")
        blocked["benchmark_candidates"] = []
        blocked["feasibility_status"] = "blocked"
        blocked["feasibility_blocker"] = "没有发布可检验核心机制的标签。"
        response = {"scope_summary": "test", "papers": [blocked, paper_record("Ready Paper")]}
        manifest = direction_research.build_manifest("方向", response, 2)
        self.assertNotIn("benchmark_candidates", manifest["papers"][0])
        self.assertEqual(manifest["papers"][0]["feasibility_status"], "blocked")

    @mock.patch("direction_research.generate_idea.subprocess.run")
    @mock.patch("direction_research.generate_idea.resolve_codex_cli")
    def test_execute_agent_enables_live_search(self, resolve_cli, run):
        resolve_cli.return_value = direction_research.Path("codex.exe")

        def fake_run(command, **kwargs):
            output_index = command.index("--output-last-message") + 1
            output_path = direction_research.Path(command[output_index])
            response = {
                "scope_summary": "test",
                "papers": [paper_record("Paper One"), paper_record("Paper Two")],
            }
            output_path.write_text(__import__("json").dumps(response), encoding="utf-8")
            return mock.Mock(returncode=0, stdout="", stderr="")

        run.side_effect = fake_run
        direction_research.execute_research_agent("医学 VLM", 2)
        command = run.call_args.args[0]
        self.assertEqual(command[1], "--search")
        self.assertIn("--output-schema", command)

    @mock.patch("direction_research.generate_idea.subprocess.run")
    @mock.patch("direction_research.generate_idea.resolve_codex_cli")
    def test_execute_agent_repairs_invalid_research_response(self, resolve_cli, run):
        resolve_cli.return_value = direction_research.Path("codex.exe")
        prompts = []
        invalid_paper = paper_record("Paper One")
        invalid_paper["benchmark_candidates"] = []
        responses = [
            {
                "scope_summary": "test",
                "papers": [invalid_paper, paper_record("Paper Two")],
            },
            {
                "scope_summary": "test",
                "papers": [paper_record("Paper One"), paper_record("Paper Two")],
            },
        ]

        def fake_run(command, **kwargs):
            prompts.append(kwargs["input"])
            output_index = command.index("--output-last-message") + 1
            output_path = direction_research.Path(command[output_index])
            output_path.write_text(json.dumps(responses[len(prompts) - 1]), encoding="utf-8")
            return mock.Mock(returncode=0, stdout="", stderr="")

        run.side_effect = fake_run
        manifest = direction_research.execute_research_agent("医学 VLM", 2)

        self.assertEqual(len(manifest["papers"]), 2)
        self.assertEqual(len(prompts), 2)
        self.assertIn("no verified core-task benchmark", prompts[1])
        self.assertIn("Do not add adjacent papers", prompts[1])


if __name__ == "__main__":
    unittest.main()
