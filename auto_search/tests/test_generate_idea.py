from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import generate_idea


VALID_MARKDOWN = """# Idea: Plain Test Method

## Weakness
Small targets disappear in deep features, which prevents reliable prediction.

## Root-Cause Analysis

### Cause (1): **Detail dilution**
Local evidence is averaged with dominant background features.

### Cause (2): **Scale mismatch**
Fixed-resolution processing does not adapt to target size.

### Cause (3): **Training imbalance**
Background pixels dominate optimization after the first two failures occur.

Together, the causes remove evidence before the final prediction.

## Contribution

\\noindent \\textbf{(1)} For Cause (1) "Detail dilution", we propose \\textbf{a high-resolution residual path} that preserves local evidence.

\\noindent \\textbf{(2)} For Cause (2) "Scale mismatch", we construct \\textbf{multi-scale feature selection} that selects a suitable resolution.

\\noindent \\textbf{(3)} For Cause (3) "Training imbalance", we introduce \\textbf{lesion-level hard-negative sampling} that balances useful gradients.

## Method

### Contribution (1) Implementation
This component addresses Detail dilution.

**Input:** An early high-resolution feature map.

**Processing Steps:**
1. Project the feature channels with a convolution.
2. Preserve the projected map beside the encoder.
3. Align it with the next decoder stage.

**Output:** A spatially aligned local feature map.

**Handoff:** The map enters Contribution (2) as one feature scale.

### Contribution (2) Implementation
This component addresses Scale mismatch.

**Input:** The local feature map and backbone features.

**Processing Steps:**
1. Align all feature maps to the decoder resolution.
2. Estimate location-wise scale weights with standard attention.
3. Fuse the weighted feature maps.

**Output:** A scale-selected feature map.

**Handoff:** The map enters Contribution (3) and the prediction head.

### Contribution (3) Implementation
This component addresses Training imbalance.

**Input:** The scale-selected feature map and training labels.

**Processing Steps:**
1. Form lesion-level training groups from the labels.
2. Sample hard background regions near lesion boundaries.
3. Compute the standard task loss on the balanced groups.

**Output:** A trained prediction head with balanced supervision.

**Handoff:** The prediction head produces the final task output.

### Datasets and Benchmark

**Datasets**

#### Dataset (1): [Training Segmentation Set](https://example.org/training-set)

**Usage Stage:** Train the evidence-preservation path and prediction head.

**Released Content:** Images, class labels, masks, and the official split.

**Usage Method:** Use released masks for task supervision and deterministic size grouping.

**Benchmarks**

#### Benchmark (1): [Direct Segmentation Benchmark](https://example.org/benchmark-one)

**Task Type:** Segmentation.

**Usage Mode:** Direct use of the official test split and metrics.

**Evaluation Method:** Report Dice, sensitivity, and trace retention.

**Mapped Contributions:** Test Contributions (1) and (2) through local evidence and scale diagnostics.

#### Benchmark (2): [Detection Transfer Benchmark](https://example.org/benchmark-two)

**Task Type:** Detection.

**Usage Mode:** Direct use of the released detection protocol.

**Evaluation Method:** Report average precision and small-target recall.

**Mapped Contributions:** Test Contributions (1) and (3) through small-target recall and false positives.

#### Benchmark (3): [Robust Classification Benchmark](https://example.org/benchmark-three)

**Task Type:** Classification robustness.

**Usage Mode:** Adapted use with deterministic resizing from released images, retained labels, source-group split isolation, and fixed seeds because the original protocol lacks size stress tests.

**Evaluation Method:** Report balanced accuracy and performance across deterministic size strata.

**Mapped Contributions:** Test Contribution (3) and the complete interaction under distribution shift.

**Downstream Tasks:**
1. Segmentation: Direct Segmentation Benchmark.
2. Detection: Detection Transfer Benchmark.

**Annotation Source:** Use only released annotations; no new doctor annotation, review, rating, or adjudication is required.

**Gaps and Handling:** Limit the claim to the released modality and label space.

### Complete Implementation Process
**Overall Mechanism:** The image passes through evidence preservation, scale selection, and balanced prediction in one ordered path.

**Data Preparation:** Use released images, masks, and the original benchmark split with deterministic resizing.

**End-to-End Steps:**
1. Initialize the released backbone and standard prediction head.
2. Build the high-resolution residual path from early features.
3. Align the residual feature with all backbone scales.
4. Learn scale weights from released task supervision.
5. Form balanced lesion and background training groups.
6. Optimize the complete path and deploy it without location annotations.

**Final Outputs:** Produce the task prediction, confidence, and evidence trace measured by released segmentation labels.
"""


VALID_PASS_MARKDOWN = """# PASS: No benchmark supports the mechanism

## Weakness
The weakness requires local evidence retention to be evaluated independently.

## Benchmark Audit
**Checked:** Public classification datasets without localization labels.

**Direct Support:** None can test the required local evidence outcome.

**Adaptability:** Image transforms preserve class labels but cannot create localization truth.

**New Doctor Annotation:** New doctor review would be required and is prohibited.

**Minimum Resources:** The estimated compute fits one GPU, but annotation remains blocking.

## PASS Decision
**Blocker:** No released label or deterministic adaptation can evaluate the core mechanism.

**Decision:** PASS
"""


class GenerateIdeaTests(unittest.TestCase):
    def test_cancellable_command_stops_running_process(self):
        cancel_event = threading.Event()
        timer = threading.Timer(0.15, cancel_event.set)
        timer.start()
        try:
            with self.assertRaises(generate_idea.ProcessCancelledError):
                generate_idea.run_command(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    "",
                    timeout=5,
                    cancel_event=cancel_event,
                )
        finally:
            timer.cancel()

    def test_render_prompt_inserts_weakness_and_language(self) -> None:
        prompt = generate_idea.render_prompt("跨场景性能下降", "zh")
        self.assertIn("跨场景性能下降", prompt)
        self.assertIn("Simplified Chinese", prompt)
        self.assertIn("No component may require", prompt)
        self.assertIn("how gradients reach it", prompt)
        self.assertIn("Keep training and inference interfaces consistent", prompt)
        self.assertIn("at least three candidate solutions", prompt)
        self.assertIn("closest obvious baseline", prompt)
        self.assertIn("does not by itself count as novelty", prompt)
        self.assertIn("Distinguish output dependence from semantic correctness", prompt)
        self.assertIn("may not supervise or validate itself", prompt)
        self.assertIn("Do not require any new annotation", prompt)
        self.assertIn("Return PASS when", prompt)
        self.assertIn("currently confirmed evidence", prompt)
        self.assertIn("# PASS:", prompt)
        self.assertIn("Datasets and Benchmark", prompt)
        self.assertIn("one or more named public benchmarks", prompt)
        self.assertIn("fewer than three benchmarks", prompt)
        self.assertIn("at least two distinct downstream task types", prompt)
        self.assertIn("official-primary-url", prompt)
        self.assertIn("Complete Implementation Process", prompt)
        self.assertNotIn("### Resource Budget", prompt)
        self.assertNotIn("### Training Procedure", prompt)
        self.assertNotIn("{{WEAKNESS_JSON}}", prompt)

    def test_render_prompt_encodes_template_like_input_as_data(self) -> None:
        weakness = 'Text with "quotes" and {{LANGUAGE_INSTRUCTION}}'
        prompt = generate_idea.render_prompt(weakness, "en")
        self.assertIn('\\"quotes\\"', prompt)
        self.assertIn("{{LANGUAGE_INSTRUCTION}}", prompt)

    def test_clean_markdown_removes_outer_fence(self) -> None:
        fenced = f"```markdown\n{VALID_MARKDOWN.rstrip()}\n```"
        self.assertEqual(generate_idea.clean_markdown(fenced), VALID_MARKDOWN)

    def test_validate_markdown_accepts_mapped_structure(self) -> None:
        generate_idea.validate_markdown(VALID_MARKDOWN)

    def test_validate_markdown_accepts_pass_structure(self) -> None:
        generate_idea.validate_markdown(VALID_PASS_MARKDOWN)
        self.assertTrue(generate_idea.is_pass_markdown(VALID_PASS_MARKDOWN))

    def test_validate_markdown_rejects_incomplete_pass_audit(self) -> None:
        invalid = VALID_PASS_MARKDOWN.replace("**Adaptability:**", "**Adaptation:**", 1)
        with self.assertRaisesRegex(ValueError, "required fields"):
            generate_idea.validate_markdown(invalid)

    def test_validate_markdown_rejects_incomplete_response(self) -> None:
        with self.assertRaises(ValueError):
            generate_idea.validate_markdown("# Idea\n\n## Weakness\nText.\n")

    def test_validate_markdown_rejects_formula(self) -> None:
        with self.assertRaisesRegex(ValueError, "mathematical notation"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace(
                    "Small targets disappear",
                    r"The update is $x = y + z$ and small targets disappear",
                    1,
                )
            )

    def test_validate_markdown_requires_three_contributions(self) -> None:
        with self.assertRaisesRegex(ValueError, "numbered"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace(r"\noindent \textbf{(3)}", "Missing third:")
            )

    def test_validate_markdown_requires_latex_bold_method_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "LaTeX textbf"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace(
                    r"\textbf{multi-scale feature selection}",
                    "**multi-scale feature selection**",
                )
            )

    def test_validate_markdown_requires_point_to_point_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "matching cause"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace('Cause (2) "Scale mismatch"', "the second cause", 1)
            )

    def test_validate_markdown_rejects_wrong_section_order(self) -> None:
        invalid = VALID_MARKDOWN.replace("## Contribution", "## Method Draft", 1)
        with self.assertRaisesRegex(ValueError, "exactly Weakness"):
            generate_idea.validate_markdown(invalid)

    def test_validate_markdown_requires_method_interfaces(self) -> None:
        with self.assertRaisesRegex(ValueError, "input, processing steps, output, and handoff"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace("**Handoff:**", "**Next:**", 1)
            )

    def test_validate_markdown_requires_complete_process_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "required fields"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace("**Overall Mechanism:**", "**Main Design:**", 1)
            )

    def test_validate_markdown_requires_benchmark_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "required fields"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace("**Mapped Contributions:**", "**Evaluation Mapping:**", 1)
            )

    def test_validate_markdown_requires_at_least_one_linked_benchmark(self) -> None:
        start = VALID_MARKDOWN.index("#### Benchmark (1):")
        end = VALID_MARKDOWN.index("**Downstream Tasks:**")
        invalid = VALID_MARKDOWN[:start] + VALID_MARKDOWN[end:]
        with self.assertRaisesRegex(ValueError, "at least one linked benchmark card"):
            generate_idea.validate_markdown(invalid)

    def test_validate_markdown_accepts_one_linked_benchmark(self) -> None:
        start = VALID_MARKDOWN.index("#### Benchmark (2):")
        end = VALID_MARKDOWN.index("**Downstream Tasks:**")
        one_benchmark = VALID_MARKDOWN[:start] + VALID_MARKDOWN[end:]
        generate_idea.validate_markdown(one_benchmark)

    def test_validate_markdown_requires_distinct_benchmark_links(self) -> None:
        invalid = VALID_MARKDOWN.replace(
            "https://example.org/benchmark-two",
            "https://example.org/benchmark-one",
            1,
        )
        with self.assertRaisesRegex(ValueError, "distinct names and official URLs"):
            generate_idea.validate_markdown(invalid)

    def test_validate_markdown_requires_two_downstream_tasks(self) -> None:
        invalid = VALID_MARKDOWN.replace(
            "2. Detection: Detection Transfer Benchmark.\n",
            "",
            1,
        )
        with self.assertRaisesRegex(ValueError, "at least two distinct numbered task types"):
            generate_idea.validate_markdown(invalid)

    def test_validate_markdown_does_not_count_two_benchmarks_as_two_tasks(self) -> None:
        invalid = VALID_MARKDOWN.replace(
            "2. Detection: Detection Transfer Benchmark.",
            "2. Segmentation: Detection Transfer Benchmark.",
            1,
        )
        with self.assertRaisesRegex(ValueError, "at least two distinct numbered task types"):
            generate_idea.validate_markdown(invalid)

    def test_chinese_dataset_benchmark_contract_accepts_three_benchmarks(self) -> None:
        body = """**数据集**

不使用额外训练或构建数据集。

**Benchmark**

#### Benchmark (1)：[基准一](https://example.org/zh-b1)
**任务类型：** 分割。
**使用方式：** 直接使用原始测试集。
**评测方法：** Dice。
**对应贡献：** Contribution (1)。

#### Benchmark (2)：[基准二](https://example.org/zh-b2)
**任务类型：** 检测。
**使用方式：** 直接使用原始测试集。
**评测方法：** AP。
**对应贡献：** Contribution (2)。

#### Benchmark (3)：[基准三](https://example.org/zh-b3)
**任务类型：** 分类。
**使用方式：** 改造后使用固定缩放并保持原标签和划分隔离。
**评测方法：** Balanced accuracy。
**对应贡献：** Contribution (3)。

**下游任务：** 不涉及下游任务：三个基准直接验证核心任务。

**标注来源：** 只使用发布标注。

**缺口与处理：** 结论限定于公开模态。
"""
        generate_idea.validate_dataset_benchmark_section(body, "zh")

    def test_validate_markdown_requires_six_process_steps(self) -> None:
        with self.assertRaisesRegex(ValueError, "six to ten"):
            invalid = VALID_MARKDOWN.replace(
                "6. Optimize the complete path and deploy it without location annotations.\n",
                "",
                1,
            )
            generate_idea.validate_markdown(invalid)

    def test_validate_markdown_rejects_removed_legacy_sections(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing or out of execution order"):
            generate_idea.validate_markdown(
                VALID_MARKDOWN.replace(
                    "### Complete Implementation Process",
                    "### Training Procedure\nLegacy text.\n\n### Complete Implementation Process",
                    1,
                )
            )

    def test_run_codex_reads_last_message(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            output_index = command.index("--output-last-message") + 1
            Path(command[output_index]).write_text(VALID_MARKDOWN, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(generate_idea, "resolve_codex_cli", return_value=Path("codex.exe")):
            with patch.object(generate_idea.subprocess, "run", side_effect=fake_run):
                result = generate_idea.run_codex("prompt", model=None, timeout=30)
        self.assertEqual(result, VALID_MARKDOWN)
        self.assertEqual(commands[0][1], "--search")
        model_index = commands[0].index("--model") + 1
        self.assertEqual(commands[0][model_index], generate_idea.DEFAULT_CODEX_MODEL)

    def test_run_codex_repairs_invalid_markdown(self) -> None:
        commands: list[list[str]] = []
        prompts: list[str] = []
        responses = ["# Idea: Invalid\n\n## Weakness\nIncomplete.\n", VALID_MARKDOWN]

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            prompts.append(str(kwargs["input"]))
            output_index = command.index("--output-last-message") + 1
            Path(command[output_index]).write_text(responses[len(commands) - 1], encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(generate_idea, "resolve_codex_cli", return_value=Path("codex.exe")):
            with patch.object(generate_idea.subprocess, "run", side_effect=fake_run):
                result = generate_idea.run_codex("original prompt", model=None, timeout=30)

        self.assertEqual(result, VALID_MARKDOWN)
        self.assertEqual(len(commands), 2)
        self.assertEqual(prompts[0], "original prompt")
        self.assertIn("Mandatory format repair", prompts[1])
        self.assertIn("Document must contain exactly Weakness", prompts[1])

    def test_atomic_write_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "idea.md"
            generate_idea.write_text_atomic(output, "first\n")
            with self.assertRaises(FileExistsError):
                generate_idea.write_text_atomic(output, "second\n")
            generate_idea.write_text_atomic(output, "second\n", force=True)
            self.assertEqual(output.read_text(encoding="utf-8"), "second\n")

    def test_preflight_finds_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "idea.md"
            output.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                generate_idea.ensure_writable([output], force=False)
            generate_idea.ensure_writable([output], force=True)


if __name__ == "__main__":
    unittest.main()
