# Run AutoDesign

AutoDesign has two phases, in this order:

```text
DESIGN  →  RUN
```

Design decides what experiments exist and what effect each one should achieve. Run implements and executes them, then compares observation against the design's targets. Do not interleave scientific design and implementation: write no experiment code before the design's coverage audit says `PASS`, and add or redefine no experiment during execution. A downstream AutoWriting module may draft from the published design handoff while Run proceeds; writing never changes the accepted experiment design.

Apply this precedence throughout:

```text
scientific intent > evidence eligibility > execution completeness > presentation
```

A completed pipeline that changed the Idea or evaluated it with ineligible evidence is not a successful scientific run.

## Accept the input

The upstream module is **AutoSearch**, owned outside this repository. AutoDesign requires **Motivation** and **Contribution**. **Benchmark** is optional input: when supplied it is a scientific lock; when absent the design worker selects or designs it from the contributions.

Two input channels are equally valid:

- a canonical `autosearch_handoff.json` in the run directory or `assets/input/`;
- natural language in the conversation — this is normal usage, for example an uploaded Idea file containing the motivation and contributions, with an optional benchmark written out in prose.

The user may also supply a benchmark, an initial experiment plan, preferred baselines, compute limits, related work, or explicit constraints. Absorb everything supplied; never discard information because no schema field matches it, and never demand a JSON file when Motivation and Contribution are already present in the request. Stop with a blocker only when Motivation or Contribution is genuinely absent.

`design` owns normalization into `input_brief.md`. Read `auto_design/prompts/references/autodesign-flow.md` for the run layout, state vocabulary, and invalidation rules.

## Locate the run

Different projects may run their controllers concurrently. This does not grant exclusive access to GPUs or shared resources: before launching experiments, inspect current usage and obey this task’s GPU selection, concurrency and remaining-budget constraints. Do not stop another project’s processes.

Use the selected project workspace and runtime paths injected by the Python service. All workers and tools ship inside auto_design/. No installed Skills are needed. Put inputs, logs and outputs below assets/ and documentation below docs/.

When resuming the same Idea and run, read these first when present:

- `AUTODESIGN_STATE.md`
- `input_brief.md`
- `experiment_design.md`
- `expected_effects.json`
- `r0_record.json`
- `implementation_notes.md`
- `execution_record.json`
- `result_summary.json`
- `effect_comparison.md`
- `result_diagnosis.md`
- `result_route.md`
- `next_round.md`
- `integrity_audit.md`

Resume from the first unfinished or invalidated stage. Do not rerun an expensive completed stage unless its input artifact changed. Design and execute fresh experiments for the supplied Idea; never copy pre-existing observations into a new run as a substitute for executed evidence.

## Dispatch

The Python application dispatches independent Codex CLI calls for design, run, diagnosis and audit. Complete only the action selected in TASK_CONTEXT_JSON; do not invoke another agent, installed Skill, or downstream stage yourself. Read the referenced local prompt documents as ordinary files when needed.

**Phase 1 — Design.** Follow `design`. It normalizes the handoff into `input_brief.md`, derives contribution-to-benchmark requirements, selects direct reuse, adaptation, or new construction, selects the method route, designs the `main`, `ablation`, `case_study`, and `analysis` experiments, plans paper-facing result tables before target effects, and writes `experiment_design.md` plus `expected_effects.json` with a simulated target and decision threshold for every claim-relevant decision effect. Baseline and presentation-only aggregates remain in the table and schedule without fake target entries. The design ends with `## AutoWriting handoff`. It writes `r0_plan.md` when a method choice or adapted/new benchmark needs a low-cost gate.

**Phase 1b — R0, only when required.** Dispatch `run` to execute the R0 probe and return `r0_record.json`, then return to `design` to accept or revise the route. The probe compares each registered high-impact choice itself, and any fit/materialization IDs are disjoint from candidate-selection IDs and later claim-bearing evaluation. A failed R0 revises the design; it never silently switches the full experiment.

**Design → AutoWriting handoff, without blocking Run.** Publish the handoff as soon as Design finishes:

- Use `ACCEPTED` when no R0 remains and the coverage audit says `PASS`. Hand off `input_brief.md`, `experiment_design.md`, and the read-only `expected_effects.json` through the environment's normal downstream-module mechanism, then continue to Phase 2 without waiting for writing.
- Use `PROVISIONAL_WAITING_FOR_R0` when R0 can still change the route and require the coverage audit to declare the same verdict. AutoWriting may draft motivation, contribution, stable method context, experiment setup, table shells, and figure plans, but it must keep route-dependent prose and values conditional. After R0, republish the revised accepted handoff and name the affected sections and entry IDs.
- If no AutoWriting module is available in the current environment, report that the handoff is ready and continue Run. Do not add a new AutoDesign state or block execution on writing progress.
- Use `{{RESULT:<experiment_id>::<variant_id>::<benchmark_task_id>::<metric>}}` for absolute aggregate cells and `{{EFFECT:<entry_id>}}` only for an optional derived comparison. A numeric simulated target may appear only in a document visibly marked `DRAFT — SIMULATED TARGETS, NO OBSERVED RESULTS`, with `SIMULATED_TARGET` in the same cell or caption. It never appears as an observed fact, final claim, or submission-ready result.

**Phase 2 — Run.** Follow `run`. It materializes `generated_project/`, writes `command_plan.json`, `experiment_schedule.json`, and `result_contract.json`, executes `preflight → smoke → experiment → aggregate → collect`, ingests results, and writes `effect_comparison.md` comparing observed values against the design's simulated targets.

**Phase 3 — Result science.** Follow `diagnosis`. It checks evidence eligibility before behavior, assigns contribution verdicts, and writes `result_route.md`.

An interrupted or incomplete run may enter result science for engineering diagnosis and recovery planning without passing scientific-readiness gates. If the user explicitly requests diagnosis only, stopping execution, or conservative reporting, finish that requested delivery without dispatching new experiments. Materialize the reporting plan when reporting is requested, retain visible evidence gaps and open actions, and preserve the last accepted state. The dispatch and final-completion rules below govern the full experimental pipeline; a scoped diagnostic/reporting delivery does not close that pipeline or authorize an integrity `PASS`.

**Phase 4 — Route closure.** Read `result_route.md` and dispatch its owner worker. An iteration or execution-required tuning action must pass back through design or implementation repair, execution, ingestion, and a fresh diagnosis. Reporting-only tuning, `stop`, and `report` proceed to report materialization only when no experimental action remains open.

For a mixed or negative but complete result, do not default directly to reporting when a concrete optimization hypothesis remains. The result scientist may propose a post-result tuning round that improves the proposed method on training/validation evidence or strengthens a baseline for fairness. Freeze its search space, budget, selection split, confirmation scope, and stop rule before execution; use a new round identity and retain every previous observation. A tuning proposal that changes the method, comparison protocol, or post-result baseline search requires the same Revision-ID human approval used for a Level 2 method revision.

Observed result artifacts are immutable evidence. Never edit raw values, aggregates, uncertainty, seed membership, or paper-table numbers to make the method look better. New paper-facing numbers require a traceable fresh execution record and raw results. A projected value may appear only as a visibly labeled simulated planning value and never as an observation.

**Phase 5 — Report materialization.** Materialize every table, figure, case-study panel, and analysis output named by the accepted design's reporting plan under `reports/`, then write `reports/report_manifest.json` and a human-readable `reports/index.html`. A mixed, negative, stopped, or conservative result does not waive this phase. Each planned output must either contain observed evidence or visibly state `INCOMPLETE`/`N/A` and the exact missing source or unsupported contract; a planned output may never be silently absent. Keep diagnostic-only values visibly separate from paper-eligible cells.

**Phase 6 — Independent audit.** Follow `audit`; require a literal `Verdict: PASS`.

## Close result routes

- A method-selection defect, missing evidence, redesigned experiment, or changed experiment set returns to `design`.
- A code, configuration, data-preparation, metric, seed, or command change returns to `run`.
- An unchanged-input execution or transport retry returns to `run` for execution only.
- After every fresh or corrected execution, ingest results, recompare effects, and rerun `diagnosis`.
- When iteration or tuning is selected, the result scientist loads its bundled `result_tuning_prompt.md` as the action planner; do not reconstruct that prompt here.
- When no new execution is required, preserve the route decision and proceed to `audit`.

## Recover execution breakpoints

An **execution breakpoint** is a blocking implementation or execution failure after an accepted design, such as a failed preflight, smoke, experiment, aggregate, or collect stage. It is not automatically an R0: R0 resolves a preregistered scientific uncertainty before formal execution, while breakpoint recovery preserves or deliberately revises an already accepted method.

Use two recovery levels. Boundary repair has no fixed numeric attempt limit. Keep every attempted change and result in `breakpoint_recovery.md`, and continue while another admissible boundary-only repair exists or the latest attempt produced observable progress. Unless the user sets a different value before recovery begins, use `method_revision_limit: 2` per Idea.

**Level 1 — boundary repair without changing the Idea or method.** Dispatch `run`. It may change only execution or implementation boundary conditions that preserve the accepted intervention, outcome-impacting identities, evidence class, benchmark protocol, comparison budget, schedule semantics, and claim interpretation. Examples include device placement, an equivalent effective batch through batch size plus gradient accumulation, worker count, checkpoint/resume cadence, a non-locked timeout, a literal path/configuration defect, or a compatible dependency repair. Learning objective, method component, data eligibility/composition, benchmark/split/metric, teacher/judge, prompt/tool policy, decoding budget, seed plan, or another outcome-impacting choice is not a boundary repair merely because it is written as a parameter.

Each attempt records the breakpoint ID and failed stage, literal evidence, diagnosis, exact change, why the scientific identity is unchanged, affected command, result, and next action. Resume from the first affected stage and retain the unchanged successful prefix. Do not repeat an unchanged command against the same unchanged failure indefinitely: another attempt needs a materially different admissible repair, new evidence, or measurable progress. Level 1 ends only when no remaining boundary-only repair can plausibly address the observed failure, not because an arbitrary retry count was reached; do not relabel scientific changes as parameter tuning.

**Level 2 — minimal method revision with human approval.** `run` writes `method_revision_request.md`; `design` responds with `method_revision_proposal.md`. The proposal must preserve the literal Motivation, Contribution, supplied Benchmark locks, and as much of the accepted method as possible; state one smallest method delta that addresses the observed breakpoint, its falsifier, affected experiments/artifacts, expected cost, and rollback condition. It is a proposal, not authorization: do not edit the accepted design or implementation until the user approves that exact `Revision ID`.

Before exposing Yes/No, verify that the proposal contains a self-contained Chinese approval summary under the exact headings `## 审核背景`, `## 具体修改方法`, `## 设计思路`, and `## 实验验证`. The four sections must explain the background, precise delta and frozen scope, scientific reasoning, validation cells and decision rule, cost, and rollback in language a Chinese-speaking reviewer can understand. Keep only technical identifiers and literal contract values in English. If any section is missing or English-only, remain at the approval breakpoint but block the decision controls and return to `design` to complete the Chinese summary; never ask the user to approve unreadable text.

Advance to `WAITING_FOR_METHOD_REVISION_APPROVAL`. Prefer an available native control permitted for approvals; when none is available, show the same complete Chinese proposal and `Revision ID` in chat and directly request explicit approval. Before the method-revision limit, distinguish `批准最小方法修改` from `暂不批准`. At or above the limit, do not silently create another round: distinguish `批准一次例外修改` from `废弃当前 Idea`; the user may also postpone the decision. Use buttons when supported, otherwise accept a clear chat response referring to the displayed proposal. Never infer approval from silence or from the user's earlier authorization to run experiments.

Write the literal user response, its corresponding existing decision value (`APPROVE_MINIMAL_METHOD_REVISION`, `APPROVE_EXCEPTION_METHOD_REVISION`, `REJECT_METHOD_REVISION`, or `ABANDON_IDEA`), and matching `Revision ID` to `method_revision_decision.md`. Map a chat response only when it unambiguously identifies the decision and displayed proposal; postponement leaves approval pending. An approval increments the method-revision counter, starts a new boundary-recovery sequence while preserving all earlier attempts, returns through `design`, and invalidates affected downstream implementation and results. If the user chooses `废弃当前 Idea`, write `idea_abandonment.md`, preserve the final breakpoint, attempt history, proposal, and reusable artifacts, and advance to terminal state `IDEA_ABANDONED`. Abandonment is a workflow decision, not automatically a negative scientific result.

If an approved method revision introduces a new unresolved high-impact scientific choice, route it through the ordinary design/R0 gate. Breakpoint recovery never self-authorizes or substitutes for R0.

## Apply gates

- **Handoff gate**: Motivation and Contribution are present and preserved verbatim; any supplied Benchmark and extra input are preserved and classified; a missing Benchmark is routed to design rather than treated as a blocker.
- **Design gate**: `experiment_design.md` declares `PASS` only when benchmark requirement coverage and the benchmark decision are closed and no high-impact choice remains unresolved, or `PROVISIONAL_WAITING_FOR_R0` when an otherwise complete design has a registered method or benchmark-validity R0. Every outcome-impacting route role is closed against the locks and autonomous-choice table; no R0 candidate weakens a scientific lock; every `CLAIM_BEARING` experiment states the exact estimand that isolates its mapped claim; every contribution and derived axis has a falsifier; all four families are populated or every absent family has a reason under `## Absent families`; every case study has a pre-result selection rule with failure categories; every selected baseline has a fairness plan and appears in a main experiment.
- **Table and target gate**: the primary table shows absolute results for selected baselines and the proposed method over the locked evaluation scope; ablation and focused-analysis tables preserve the exact comparison they claim to answer. Every decision effect has an `expected_effects.json` entry with `value_status: SIMULATED_TARGET`, a literal `decision_threshold`, a `target_basis`, and an `on_miss` route. A simulated target may appear only in an explicitly marked AutoWriting draft; it never appears in `reports/`, a submission-ready table or figure, an observed result, or a claim verdict.
- **Idea-consistency gate**: the route preserves the user's scientific locks and operational meaning; subset implementations remain pilots or ablations rather than winning R0 as the full method; unstated roles and choices remain explicit design decisions rather than retroactive additions to the Idea.
- **R0 gate**: a required method-choice R0 has an executed record covering every high-impact autonomous choice not resolved by the user, comparing at least two candidate instantiations of that choice rather than a proxy. A benchmark-validity R0 tests construction and measurement feasibility without selecting the benchmark on proposed-method performance. Fit/materialization, candidate-selection, and later claim-bearing IDs remain disjoint. A design-authored `passed` string or a single documented default is not evidence, and R0 success alone never supports a contribution.
- **Implementation gate**: every accepted experiment across all four families has a runnable entrypoint, complete environment, decision-relevant preflight, result path, and observed chart path. Preflight compares planned and materialized scientific identities, data composition, benchmark provenance, and protocol values before expensive execution.
- **Execution gate**: `preflight → smoke → experiment → aggregate → collect` all exit zero under the current commands.
- **Breakpoint-recovery gate**: boundary repairs preserve the accepted scientific identity and have no fixed numeric cap; they continue only while a materially different admissible repair, new evidence, or measurable progress exists. Every method revision has a matching human decision, and no execution uses an unapproved revision. At the method-revision limit, offer `废弃当前 Idea` through an available approval control or the chat fallback.
- **Result gate**: observed cells equal scheduled experiment × variant × task × seed cells and planned metrics, no unexpected cell is silently absorbed, each result preserves its family, evidence class, and benchmark provenance, and `result_summary.json.status` is `READY_FOR_GPT_DIAGNOSIS`.
- **Comparison gate**: `effect_comparison.md` covers every design entry with a threshold outcome, retains every `MISSED` and `NOT_EVALUABLE` row, and reports no post-hoc edit to a simulated target.
- **Route-closure gate**: `result_route.md` exists, every required action is executed and rediagnosed or explicitly closed by its threshold, and expected deltas are never reported as observations.
- **Report-materialization gate**: every output named in the accepted reporting plan exists under `reports/`; `reports/report_manifest.json` records each output's source IDs and status as `READY`, `INCOMPLETE`, or `N/A`; incomplete evidence is visible at the planned output path rather than omitted; and `reports/index.html` links the complete bundle.
- **Integrity gate**: claims, runs, aggregates, tables, figures, and conclusions agree without hiding negative or mixed results.

## Maintain state

After each stage, run `python3 -m auto_design advance` to update `AUTODESIGN_STATE.md` with the current stage, last completed stage, blocking condition, next worker, changed input artifact, produced artifacts, and the literal decision and reason. Append one history row rather than rewriting scientific history; keep failed routes and negative evidence visible. Pass literal values directly — the state writer escapes table delimiters so agent text cannot break the History column.

If table whitespace or alignment was edited by hand, run `python3 -m auto_design repair-state <run_dir>` before resuming. `INTEGRITY_AUDIT_PASS` and `COMPLETE` require a literal `Verdict: PASS`; `WAITING_FOR_R0` keeps `INPUT_READY` as the last accepted milestone, while other in-progress states keep their previous completed milestone.

## Finish

The user's requested diagnostic or conservative-report delivery may finish with explicit evidence gaps and an open scientific route. Keep that delivery separate from full experiment completion: do not remove required experiments, change their eligibility, or mark the run `COMPLETE` merely because its report exists.

Full experimental pipeline completion requires:

- both phases and all post-stages through integrity audit are complete;
- no required artifact is missing;
- every required claim-bearing experiment is complete or a valid preregistered kill threshold has been crossed;
- no pilot or smoke substitutes for missing claim-bearing evidence;
- execution and result completeness pass;
- `effect_comparison.md` covers every design entry;
- the latest accepted AutoWriting handoff identifies every absolute aggregate by its result key and every optional derived comparison by `entry_id`, and contains no value presented as observed;
- every accepted reporting-plan output is materialized and listed in `reports/report_manifest.json`, including explicit `INCOMPLETE`/`N/A` artifacts where evidence is unavailable;
- submission-ready tables and figures are backed by observed aggregates only, while diagnostic-only values are visibly labeled and excluded from claim-bearing cells;
- the latest result route is closed and no execution-required entry remains in `next_round.md`;
- `integrity_audit.md` says `PASS` with no unresolved blocker;
- `AUTODESIGN_STATE.md` ends at `COMPLETE`.

Return the run directory, AutoWriting handoff status, selected route, experiment counts per family, execution target, exact result counts, target-versus-observed outcomes, contribution verdicts, tables, figures, and unresolved scientific limitations.
