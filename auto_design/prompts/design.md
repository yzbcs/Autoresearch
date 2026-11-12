# AutoDesign Experiment Design

Design only: do not implement or run experiments. Preserve this precedence:

```text
scientific intent > evidence eligibility > design completeness > presentation
```

Read [auto_design/prompts/references/autosearch-handoff.md](auto_design/prompts/references/autosearch-handoff.md) for input normalization and [auto_design/prompts/references/design-contract.md](auto_design/prompts/references/design-contract.md) for artifact fields, identities, placeholders, and schemas.

## 1. Input locks and scope

The only required authoritative scientific intent is the AutoSearch handoff's **Motivation** and **Contribution**. Accept `autosearch_handoff.json` from the run directory or `assets/input/`, or the same two items as natural language. A user-supplied **Benchmark** is optional but authoritative: preserve it literally and treat its named scope as a scientific lock. Preserve every supplied item in `input_brief.md`; stop when Motivation or Contribution is absent or contradictory, not when Benchmark is absent.

Separate the input into:

- **scientific locks**: the stated mechanism plus any user-supplied benchmarks, splits, metrics, data, models, baselines, protocols, fairness requirements, and scope-bearing language needed to interpret a contribution;
- **autonomous choices**: unstated design decisions, each classified `high` or `low` outcome impact;
- **resource constraints**: cost limits, which never relax a lock.

A high-impact choice changes what the experiment can show, including data constructor, teacher or judge identity/protocol, backbone, or execution substrate when it affects outcomes. Except for the benchmark decision owned below, resolve it only by an explicit user decision or a registered R0 comparing at least two candidate instantiations. A default, citation, or plausibility argument does not resolve it.

Use literature to select applicable benchmarks, baselines, or components, lock benchmark protocol, and locate official implementations and model cards. Do not import unstated method configurations or outcomes, and never redefine the Idea from external material.

A disclosed lock change is still a blocker; disclosure does not make reduced evidence claim-bearing.

## 2. Benchmark decision, route, and R0

Before choosing concrete experiments, derive a **claim-to-benchmark requirements matrix** from the literal contributions. For each claim record the target construct or capability, evaluation unit, task/context, required split or generalization axis, metric/evaluator, matched comparison, and failure observation. These requirements come from the contribution, not from whichever benchmark is convenient.

Search benchmark papers, official dataset or task pages, protocol documentation, and leaderboards. Keep evidence-backed Candidate Cards with identity/version, source, covered and missing requirements, data access, protocol and metrics, reusable baselines, adaptation cost, and provenance risks. Select the smallest portfolio that covers the claims through one of three routes:

- `direct_reuse`: an existing benchmark and official protocol cover the required construct and axes without changing their meaning;
- `base_benchmark_adaptation`: an existing benchmark supplies valid source data or environment, but a contribution-required task, split, annotation, intervention, or metric must be added. Give the adaptation a distinct identity and never inherit official scores or comparability it no longer has;
- `new_benchmark_construction`: no existing benchmark can measure a required construct without invalidating the claim. Use this only for the uncovered requirement, not to manufacture a second paper contribution or generic breadth.

Audit a user-supplied benchmark against the same matrix. Preserve its locked scope and add another benchmark or a named adaptation only when a contribution would otherwise be untestable; do not silently replace or narrow it. When no benchmark is supplied, the source-backed, pre-result coverage decision is owned by this worker. Record the selected and rejected candidates and freeze the accepted benchmark identities, versions, splits, metrics, and evaluators before proposed-method results are inspected. Never select a benchmark because the proposed method scores better on it.

If candidates are equally defensible but imply different claim meanings, leave the decision unresolved for an explicit user choice or a measurement-focused R0. An adapted or new benchmark requires an R0 before claim-bearing execution. That R0 tests construction feasibility and measurement validity—such as usable sample yield, annotation or evaluator agreement, non-degenerate difficulty, metric computability, and split integrity—not the proposed method's advantage. R0 data and outcomes are pilots, never claim support.

For `base_benchmark_adaptation` or `new_benchmark_construction`, include a benchmark design record with: target construct and exclusion boundary; source population/data/environment and eligibility; task or item construction; annotation/reference/evaluator protocol; split and leakage policy; primary and diagnostic metrics; baseline calibration; reliability and validity checks; sample and cost budget; versioned identity; R0 falsifier; and claim-bearing validation experiments. If the benchmark itself is a contribution, map its quality claims to separate `CLAIM_BEARING` cards rather than treating method performance as benchmark validation.

Then choose the scientific intervention before concrete components. Record the operational meaning, observable implication, prohibited reinterpretation, and uncertainty of each central term. Treat `all`, `each`, named stages/objects/spans, and equivalent scope language as locks; a subset route is an ablation or `MECHANISM_PILOT`, not the full method.

Classify the handoff as `method_specified`, `mechanism_specified`, or `goal_only`. Preserve a specified method. For mechanism-specified or goal-only input, compare at least two route families with distinct falsifiable predictions. Give each candidate its intervention, minimal probe, falsifier, contribution/benchmark fit, cost, and rejection condition. Select only roles the route needs, then close the role inventory: every outcome-impacting backbone, constructor/teacher, judge, verifier, retriever, reward model, tool, substrate, or training loop must be a lock or a resolved autonomous-choice row before it appears downstream.

Require R0 for goal-only input, unresolved high-impact choices, and expensive routes with unresolved central feasibility. R0 is a gate, never claim support. For every comparison:

- vary only the registered high-impact choice; keep teacher/backbone, data, budget, protocol, and every other outcome-impacting axis matched, or factor the additional axis into a separate control;
- preserve every scientific lock; an R0 win cannot legalize a weakened Idea;
- if fitting, adaptation, prompt selection, or data construction occurs, keep fit/materialization IDs, candidate-selection IDs, and later `CLAIM_BEARING` IDs disjoint;
- register every cell named by a selection or kill rule, including reference cells, in the R0 execution-cell inventory with budget, command intent, outputs, metrics, and cost.

Write `r0_plan.md` when required. `run` executes it; its matching `r0_record.json` returns here for design revision. A missing or unbudgeted rule reference is an evidence gap, not an implicit free comparison.

## 2b. Minimal method revision after an execution breakpoint

When `run` returns `method_revision_request.md`, read it with `breakpoint_recovery.md` and the last accepted design. Do not reinterpret an implementation/resource failure as a method failure, and do not spend another boundary attempt inside this worker.

Write one `method_revision_proposal.md` containing the smallest method delta that can address the observed breakpoint while preserving the literal Motivation, Contribution, any supplied Benchmark lock, and every unaffected part of the accepted method. Include: stable `Revision ID`; triggering request/breakpoint and evidence; original method behavior; one proposed delta; why no remaining boundary-only repair can address the failure; preserved and changed identities; effect on claim meaning; affected design/effect/schedule/result IDs; new falsifier or R0 need; expected cost; rollback condition; boundary-repair history and approved-method-revision count; and whether the configured method-revision limit has been reached.

The human-facing approval summary must be written in clear Chinese before any detailed appendix, with these exact second-level headings in order: `## 审核背景`, `## 具体修改方法`, `## 设计思路`, and `## 实验验证`. Explain the evidence gap and why a human decision is required; what changes and what remains frozen; the causal or measurement logic and how post-hoc selection is avoided; and the exact cells, falsifier, expected cost, and rollback. Technical identifiers, dataset/model/metric names, literal decisions, and the `Revision ID` may remain in English. Do not use an English-only proposal, a file link, or “see proposal” as the approval summary.

Do not rewrite `experiment_design.md`, `expected_effects.json`, implementation, or commands before human approval of that exact `Revision ID`. Advance to `WAITING_FOR_METHOD_REVISION_APPROVAL` and return control to `orchestration`, which uses an available native control permitted for approvals or asks directly in chat with the same complete proposal and `Revision ID`. Record only an explicit user response that unambiguously refers to that proposal; silence is not approval. A matching `APPROVE_MINIMAL_METHOD_REVISION` or `APPROVE_EXCEPTION_METHOD_REVISION` in `method_revision_decision.md` authorizes only that proposal. `REJECT_METHOD_REVISION` leaves the accepted method unchanged and paused; `ABANDON_IDEA` ends the Idea without turning the breakpoint into negative scientific evidence.

After approval, increment the Idea-level approved-method-revision count, start a new boundary-recovery sequence without erasing prior attempts, revise all affected design identities explicitly, rerun the coverage audit, and invalidate downstream implementation/results. If the delta introduces an unresolved high-impact choice, register the ordinary R0 instead of treating approval as evidence. Keep the rejected/failed method version and its breakpoint visible in design history.

## 3. Claim-bearing evidence

Assign each experiment one paper family—`main`, `ablation`, `case_study`, or `analysis`—and one evidence class—`CLAIM_BEARING`, `MECHANISM_PILOT`, or `ENGINEERING_SMOKE`. Only `CLAIM_BEARING` evidence may support or refute a contribution.

Every claim-bearing experiment owns one primary research question and this **Claim Contract**:

```text
research_question
intervention
matched_reference
primary_metric
literal_falsifier
claim_collapse
```

The reference, unit, and aggregation must isolate the intervention. If the literal falsifier is met, `claim_collapse` names the exact claim to narrow or withdraw; extra interpretation cannot convert every outcome into support.

- **Main** asks whether the contribution holds on the accepted benchmark portfolio. Map every contribution to a named benchmark, split, metric, multiple seeds, and uncertainty. Close two baseline roles: `causal_reference` is matched on key axes except the target intervention and estimates its effect; `contextual_baseline` is a recognizable independent external system that positions the paper. One baseline may serve both only when both roles are justified separately. Missing either role is an evidence gap even if other baselines exist. Run selected baselines under source-backed protocols without removing their defining scaffold; a surrogate remains a named pilot and never inherits an official benchmark identity.
- **Ablation** asks which part causes the effect. Remove or substitute one mechanism component while fixing all other axes. Sample eligibility, filtering, replenishment, and composition are data-axis changes and cannot be bundled with an objective, mask, or component change. A multi-axis contrast is a design defect.
- **Case study** asks what the behavior looks like. Freeze eligible pool, sampling rule/seed, category counts, and display fields before results. When a contribution concerns failure or recovery, define one preregistered taxonomy shared with its quantitative analysis and cover recovered, unrecovered, and side-effect cases. The panel illustrates that analysis; it is not a separately cherry-picked story. For every included case study, `experiment_design.md` must contain a first-pass **case-study figure draft**, not only figure metadata and not a method-overview or main-results figure. Match the visual grammar of a paper transcript excerpt: multi-line trace text, inline `Prompt`, `Agent`, `Tool Call`, `Tool Response`, `Comment`, and `Final Outcome` labels as applicable, dashed rules between turns, and restrained emphasis on decisive evidence. Target a half-page, full-width `figure*` in a two-column arXiv-style paper: when two cases are shown, place their transcript panels left and right rather than stacking them vertically. It is not a box-and-arrow process diagram: do not default to rounded cards, flow arrows, dashboard headers, status badges, or large legends. Follow the `case_figure_plan` and `case_figure_draft` size/content budget; never require hidden chain-of-thought or invent or ellipsis-compress evidence.
- **Analysis** asks why the method works and where it breaks. Test only axes entailed by the contributions, with enough levels and matched references to identify the claimed direction, shape, robustness, or transfer. Cross-context evidence compares within-context method effects; proposed-method scores alone do not isolate transfer.

Design paper-facing tables before simulated targets. The primary table plans absolute observed results for the proposed method and selected baselines across the locked scope; plan uncertainty in the result contract, but do not fabricate its display in an empty shell. Every numeric slot in a design-time table uses only the exact typed placeholder `{{RESULT:<experiment_id>::<variant_id>::<benchmark_task_id>::<metric>}}` or, for an intentionally displayed derived effect, `{{EFFECT:<entry_id>}}`. Never write mnemonic pseudo-values such as `R ± CI`, `R+CI`, `C ± CI`, `Rate ± CI`, `Δ ± CI`, `mean ± std`, or similar confidence/dispersion text in a placeholder cell. Decide the observed-value and uncertainty rendering only after the aggregate exists. Keep internal variants in ablation/focused analysis views, define only commensurate averages, and distinguish unavailable cells from zero. A curve, distribution, or trajectory belongs in a figure when that is the actual evidence.

## 4. Artifacts and readiness

Write `experiment_design.md`, read-only `expected_effects.json`, and `r0_plan.md` only when needed. Follow the contract for the claim ledger, benchmark requirements/candidates/decision, route/R0 inventories, Claim Contracts, experiment cards, execution/aggregate/paper/decision identities, table shells, coverage audit, and JSON schema.

Pre-register one `SIMULATED_TARGET` entry per decision effect, not per seed or displayed reference cell. Each entry has a literal threshold, target basis, and `on_miss: iteration|tuning|stop`; relative thresholds name a planned reference aggregate. Simulated targets are hypotheses, never observations or claim support.

In `## AutoWriting handoff`, use `ACCEPTED` or `PROVISIONAL_WAITING_FOR_R0`, identify safe and conditional sections, provide complete result/effect placeholders, and name invalidations after R0 or design revision. Numeric draft targets require document-level `DRAFT — SIMULATED TARGETS, NO OBSERVED RESULTS` plus a same-cell/caption `SIMULATED_TARGET` label. They never enter `reports/`, observed prose, final claims, or submission-ready results.

Validate structure with:

```bash
python3 -m auto_design check-design <run_dir>
```

Top-level `status: PASS` means only that deterministic artifact structure is usable; read `declared_design_readiness` separately. End the coverage audit with exactly one verdict:

- `PASS`: locks, benchmark decision, role/baseline/R0 closure, Claim Contracts, evidence coverage, tables, targets, taxonomy links when applicable, and handoff are scientifically complete; no high-impact choice remains. Use `handoff_status: ACCEPTED` and advance to `EXPERIMENT_DESIGN_READY`.
- `PROVISIONAL_WAITING_FOR_R0`: the same design requirements hold, but registered method choices or an adapted/new benchmark await R0. Use the same handoff status and advance only to `WAITING_FOR_R0`.
- `FAIL`: any design/evidence gap remains. Name it and stay before design readiness.

An absent family needs a contribution-grounded reason under `## Absent families`; placeholder prose may satisfy the structural parser but not this scientific judgement. Update state with `python3 -m auto_design advance`. The next execution worker is `run`.

## 数据隔离检查的适用范围

隔离规则必须针对当前任务可达的具体泄漏途径，使用实际可取得的来源、样本/文档ID、图像及标注信息。配置选择与正式评测的样本和图像应独立；不同图像共享常见文字不自动构成泄漏。除非科学输入明确要求文本去污染或已有证据表明同文档复用，不得将完整页面转写、通用文本shingle相似度或无法取得的上游字段设为必过门槛。缺少与实际估计目标无关的字段，记录为核验局限，不伪装成实验失败。真实样本重叠、标签流入配置选择或正式范围改变仍须阻止执行。已有不适用门槛由design在新一轮修订并冻结，保留旧失败证据；run不得将失败改写为通过。不新增无实际用途的哈希、评分器或防御性检查。每项检查说明具体检测的失败及失败后改变的动作。
