# Stackplan: interface and product simplification specification

Design proposal · 5 November 2026 · audited branch `product-simplification`, commit `fef82ce`.

**Status: specification only; implementation requires explicit approval.** This document defines the proposed product direction. It does not describe features already delivered. It supersedes the study-planner direction in the README for future product decisions, not the README's description of current behaviour. No application, prompt, schema, test, configuration, image or deployment changes accompany it.

## 1. Executive verdict

The main problem is that the site does not make the student's next action obvious. It presents a large timetable, module tables, a separate study plan, suggestion cards, statistics and weekly accordions as competing things to inspect. A student has to understand Stackplan's output structure before finding their own work. Changing the product name or calling the plan a “to-do list” would not fix that hierarchy.

The revised design must lead with one usable list, keep secondary information inside the relevant row, and remove entire sections that do not help the student act. Preserve a restrained visual identity, but remove the decorative stack scene, large introductory headings on working screens, repeated section labels and metric cards. The initial screen should contain actual work, not a large introduction to the work.

The product direction is an **AI-generated to-do list based on the uploaded assessments**. Generated actions remain useful candidates for what to work on; the student can edit, dismiss or complete them. The main screen is the list itself, not a report about the list. Assessment facts support each task through expandable details and a secondary assessment view.

Keep the generation capability, but reduce its output and presentation. Remove hours, priority badges, summaries, highlights and workload metrics. A short task such as “Outline the project report” can be a suggestion; an invented chapter, required duration or deadline cannot become a fact. The interface must distinguish suggestions from the uploaded assessment information without covering the page in warnings.

The narrow product loop is: upload screenshots, check extracted assessments, generate a short list, then return to work through that saved list. The existing generator and recommendation API provide a starting point. Persistent task completion, task editing and safe regeneration do not exist yet; these are necessary extensions, not cosmetic checkbox changes.

### Evidence basis and limits

This audit read implementation, prompts, fixtures, tests and documentation; inspected the repository's timetable and plan screenshots and the HSC1009 source image; and read existing inference records. It did not run a new browser session, a live model request, database mutation or test suite. Screenshots illustrate presentation; current JavaScript is authoritative for interactions. Test assertions show intended contracts, not independently verified model accuracy or student benefit.

| Reference | Inspected evidence and what it establishes |
| --- | --- |
| E1 | [Frontend app](../frontend/static/app.js), [model helpers](../frontend/static/model.js), [HTML shell](../frontend/templates/index.html), [styles](../frontend/static/styles.css): upload, blocking processing, timetable, module tabs, plan, URL and saved-project behaviour. |
| E2 | [HTTP adapter](../helpers/api_helper.py), [frontend proxy](../frontend/app.py): existing routes, synchronous processing, upload limits, errors; no assessment-edit or module-update endpoint. |
| E3 | [Planning service](../src/application/planning_service.py), [AI manager](../src/ai_manager/manager.py), [transport](../src/ai_manager/qwen_client.py), [prompts](../src/ai_prompts.py): extraction stages, automatic advice, timeout, concurrency and inputs. |
| E4 | [Normalizer](../src/logic_manager/module_normalizer.py), [timing](../src/domain/assessment_timing.py), [assessment](../src/domain/assessment.py), [schedule builder](../src/logic_manager/schedule_builder.py), [ranker](../src/logic_manager/importance_ranker.py), [advice validator](../src/logic_manager/recommendation_validator.py), [rules](../src/logic_manager/rules.py): deterministic transformations and their limits. |
| E5 | [Evidence store](../src/io_manager/evidence_store.py), [submission validator](../src/io_manager/submission_validator.py): temporary image lifecycle and input validation. |
| E6 | [Schema](../database/schema.sql), [repository](../src/data_manager/postgres_repository.py), [data manager](../src/data_manager/manager.py), [serializer](../src/data_manager/serializers.py): JSONB run snapshots, recommendation history, latest-result selection and transaction boundaries. |
| E7–E10 | Historical test, grader and validation evidence was removed during the Feature #1 cleanup. References to these evidence IDs below are historical claims, not current verification. |

E10 contains two four-module runs, both reporting empty `errors` and `failures`. The baseline identifies prompt version `2026-10-12-v3`: 13 calls, 360.476 seconds elapsed, 61,714 total reported tokens. Its advice call alone took 208.042 seconds and 19,351 tokens. The second identifies `2026-11-04-v4`: nine calls, 83.418 seconds extraction and 231.176 seconds total; advice took 147.747 seconds, with 15,387 of 38,253 total tokens. The second uses a “STRUCTURED EXTRACTION” stage absent from the audited implementation. It is experimental historical evidence, **not the current pipeline or proof of a speed improvement in this branch**. Neither record establishes broad accuracy, repeatable latency or financial cost. No price conversion is justified here.

The inspected HSC1009 screenshot states a 30% quiz-group weight with Weeks 2, 4 and 6, and labels its timing column tentative. This supports preserving a group total and tentative timing; it does not support three inferred 10% weights or three confirmed deadlines. Historical interpretation also includes unnecessary speculation, such as questioning an explicitly singular discussion post. Prompt instructions alone do not guarantee faithful output.

## 2. Current functionality audit

### Why the current site is hard to read

These are interface findings from E1 and the inspected previews, not claims from a completed usability study.

| Current design | Why it gets in the way | Required simplification |
| --- | --- | --- |
| Large hero, decorative stack and repeated eyebrow/title combinations | They occupy the first view without helping students find an assessment or upload a file. | One short page title; put the form or list directly below it. Remove working-screen decoration. |
| Full timetable before any assessment rows | The grid is at least 1,200 pixels wide in CSS. Fourteen columns force short assessment names into narrow cells and require horizontal inspection. | Default to a readable generated task list across modules. Keep the assessment timetable secondary. |
| Timetable plus separate module browser | The same assessment appears twice, with details elsewhere. Students must work out which representation to use. | One primary representation. Opening a row reveals its details in place. |
| Module tabs as the only detailed browsing route | Students cannot scan work across modules without switching tabs. | Show all modules by default; use one optional module filter. |
| Prominent “View study plan” on the assessment page | The strongest action sends the student away from their actual assessments to another interpretation of them. | Make the generated list the main destination after setup, with assessment facts available through row details. |
| Suggestions, three metrics, weekly accordions and unknown-date section | Every section demands interpretation, while none is clearly the place to manage an assessment. | Keep actionable suggestions as task rows. Remove suggestion cards and metrics; retain unknown timing beside affected tasks. |
| Repeated labels such as “Suggested focus,” “Suggestions,” “Plan by week,” and “Open only what you need” | Explanatory copy competes with the information it describes. | Use direct labels: “To do,” “Done,” “Module,” “Assessment week unknown,” “Details,” “Edit.” |
| “Start again” beside a saved-project picker | It is unclear whether this resets the current result or starts a separate project. | Rename to “New trimester”; preserve the current project. |
| Important qualifications hidden while generic advice is prominent | The screen gives attention to the least reliable information. | Show only material row qualifications inline; put full source wording and technical diagnostics behind Details. |

The first redesign must solve hierarchy, duplication and navigation before adding features. A new to-do label alone is not an acceptance criterion.

### Capability decisions

| Capability | Current behaviour | Actual benefit, evidence and limitations | Verdict and reason |
| --- | --- | --- | --- |
| Trimester creation | Named project created immediately before processing; fixed 14 weeks in browser; globally unique database name. | Separates sets of modules. Empty project can remain after failure; no ownership/account model (E1, E2, E6). | **Keep** as a lightweight container, not a separate setup wizard. |
| Module metadata | Title, required credits defaulting to six, one or more screenshots; duplicate titles blocked in browser. | Title associates evidence. Credits mainly feed the ranking; default six need not be true (sample inputs use four). | **Reduce**: retain title; remove credit input with contract changes, never silently invent replacement credits. |
| Screenshot extraction | Relevance gate, interpretation and normalization per relevant module, in that order; modules run concurrently with request limit four. | Saves transcription when correct; no guaranteed transcription accuracy, crop-level attribution or review state (E3, E5). | **Strengthen** with review and correction; keep existing extraction stages initially. |
| Upload validation | Browser accepts PNG/JPEG/WebP and 49 MB combined; core accepts JPEG/PNG only, 10 MB each, dimension constraints; HTTP limit 50 MB. | Validation is necessary, but visible and actual supported formats disagree. Valid images can continue after another fails (E1, E2, E5). | **Strengthen**: align displayed constraints with real validation; expose rejected evidence. |
| Processing | One long request; global controls disabled; response awaited through extraction and automatic plan. Default pipeline timeout 1,800 seconds. | Simple lifecycle, no real progress feed, queue, resumable job or reliable completion estimate (E2, E3). | **Reduce** to separate extraction and requested checklist generation, with honest indeterminate status; facts remain accessible if generation fails. |
| Module assessment tables | One module tab at a time; name/type, week and weight; structural records labelled as group totals. | Useful reference, but hides coverage, notes, details and follow-ups; tab counts include structural group rows (E1). | **Reduce** to a secondary reference and setup review surface; count actual assessments only. |
| Week 1–14 grid | Always shown above details; same assessment appears in each active range week; links open module rows. | Shows co-occurring assessment weeks; wide grid obscures names, especially on small screens. UI does not explain `due` versus `active` versus `occurrence` (E1, E4). | **Reduce** to a secondary “Week overview”; not workload or a personal schedule. |
| Unknown dates and recurrence | Unresolved timing is kept in `unscheduled`; module rows retain raw wording; plan has “Dates to confirm.” | Correctly preserves many unknowns, but most context is hidden and dates-to-confirm is on the wrong screen (E1, E4). | **Strengthen** on assessment screen; never require opening a plan to find uncertainty. |
| Unknown weights and group totals | Individual and group weights separated; repeated items do not inherit group totals; scope labels partly displayed. | Important safeguard. Group scope is omitted by the fallback label; arbitrary finite percentages are not bounded to 0–100 by the assessment domain (E1, E4). | **Strengthen** scope display and correction validation; no equal division or synthetic totals. |
| Coverage and follow-ups | AI coverage status, notes and follow-ups survive in module metadata; ambiguous range may remain placed with a follow-up. | Useful qualification, currently mostly invisible. `appears_complete` is an AI judgement; numeric timing is not verified (E3, E4). | **Strengthen** visibility and treatment of material timing conflicts. |
| Importance ranking | Credits × explicit module-level weight / 100, globally ranked before range copies; priority is relative thirds of distinct scores. | Transparent arithmetic, but neither effort nor urgency. Missing/part/group weights are incomparable; one score gets “medium.” Not shown as an assessment badge now, but affects order and advice input (E4). | **Remove** product ranking and its effect on ordering; show source weights themselves. |
| Automatic trimester plan | Generated on every usable extraction result, stored alongside it; available through a prominent button. | Generic preparation may be plausible, but no progress, difficulty, rubric or actual availability inputs. Failure still delays factual results (E1, E3). | **Reduce**: replace automatic full-term revision planning with one short checklist generated after assessment review. Keep generation, remove the report format. |
| Suggested actions and priorities | AI action titles, weeks, hours and high/medium/low labels; validator checks references, structure, recess and hour ceiling. | These checks do not verify useful actions, accurate durations or appropriate preparation timing. Text claims are not fact-checked (E3, E4). | **Keep** short assessment-linked action suggestions; **Remove** estimated hours and priority labels. Student controls task completion and dismissal. |
| Summaries and highlights | Up to three suggestion cards; summary used as fallback. | Extra AI narrative can sound authoritative about “heavy workload”; no measured workload exists (E1, E10). | **Remove**. No replacement narrative summary. |
| Capacity and plan metrics | “Active weeks,” “Planned time,” “Actions,” weekly hours and per-task hours. `capacity()` computes exceeded flags, but current plan view does not display a capacity chart. | Counts describe generated output, not learning value. Eight-hour default is not user-provided; “with useful actions” is unsupported (E1, E4). | **Remove** metrics and misleading labels, including any dormant capacity UI proposals. |
| Recommendation history | Separate records, candidate/accepted/dismissed API and input hash. Browser chooses newest record regardless of type/status, with no revision-hash match. | No visible history/acceptance workflow; newest plan can be unrelated to current result (E1, E2, E6, E8). | **Reduce**: one active checklist per assessment revision, no history screen. Preserve older records for compatibility and safe replacement; never select newest blindly. |
| Saved projects | Picker and project URL retrieve newest non-null result, run history and all recommendations. No model call needed on reopen. | Genuine repeat use as a reference. Failed/running runs preserve old result; newer partial payload can omit previous modules; latest completion order is not revision control (E6). | **Strengthen** visible saved revision/status and safe correction persistence. |
| Manual correction | No controls, edit route, canonical edited snapshot or confirmation metadata. Tests explicitly expect old module revision routes to be absent. | Essential recovery is missing. Retrying extraction is not a correction and can change IDs/order (E2, E4, E7). | **Strengthen** through a new, bounded correction workflow; this is moderate work. |
| Original-source access | Files staged temporarily and deleted on completion; database has no durable image store or image-serving API. | Protects cleanup, but prevents reopening original evidence from saved projects (E5, E6). | **Defer** durable image library; use local session preview and explicit original-unavailable state. |
| Model cost and speed | Normally three calls per relevant successful module plus one plan call, absent retries/failures; transport logs elapsed time. | Historical traces show material advice cost in time/tokens. Current transport does not persist token/currency accounting (E3, E10). | **Reduce** repeated generation: generate once on request, reuse saved tasks, and make regeneration explicit. Shorter output is not a guaranteed latency saving; measure it. |
| Task completion and editing | No persistent task IDs, per-task done state, editor or dismissal workflow. Recommendation status applies to the entire candidate. | Essential for a usable to-do list; acceptance of a plan is not completion of its tasks (E1, E6). | **Strengthen** with durable per-task identity, completion, edit and removal. |

### Actual seven-step journey

| Step and student intent | What actually happens / what helps | Confusion, unsupported information and missing recovery |
| --- | --- | --- |
| 1. Create a trimester to collect one term | Same upload form asks for name; submission creates project, then processes. Retry reuses its ID. | “Start again” creates a new workspace, not an edit. Duplicate name fails. Empty saved projects are possible; no clear distinction between created and populated. |
| 2. Add modules and screenshots to avoid retyping | Multiple files per module; add/remove rows before submit; titles establish ownership. | Credits are unnecessary for the narrow job; WebP is offered but rejected. No source preview or persistent input draft; no post-result add-module control. |
| 3. Wait to get a result | Blocking status says screenshots, schedule and plan are being processed. | No genuine per-module progress or cancellation. User waits for speculative advice too. On request failure files remain in the current form; reload cannot restore selected local files. |
| 4. Check extracted assessments | Tabs expose names, weeks and weights; unknowns remain as text. | Coverage, notes and relevant follow-ups are not rendered. No review badge, original comparison or correction; student cannot repair AI errors. A module with zero extracted rows can still lead to an empty results view. |
| 5. Understand Weeks 1–14 | Grid places assessments and links to detail rows. | Activity range looks like repeated deadlines; fixed recess looks universal. No calendar anchor or current week. Empty cells do not establish free time. User cannot correct a placement. |
| 6. Open generated study plan to decide what to do | Suggestions, action lists, priorities and invented durations appear. | No progress or actual availability inputs; no completion tracking or execution feedback. “Actions from confirmed timing” conflates generated preparation weeks with assessment weeks. Missing plan message suggests reprocessing screenshots, but results view offers no direct reprocess action. |
| 7. Return to a saved project | Picker/URL loads persisted result without extraction; old usable result survives failed runs. | Upload warnings are transient and are not reconstructed into the assessment screen on reopen. Old recommendations can be paired with newer facts. No corrected revisions, reliable stale-write protection or way to keep the reference up to date. |

## 3. Product goal and boundary

**Primary user:** a student with assessment information scattered across module screenshots who wants a short, manageable starting list of study actions.

**Primary problem:** the current site makes the student navigate a timetable, module tables, advice cards and weekly plan sections before deciding what to do. It offers generated actions without the basic ability to manage them as tasks.

**One-sentence purpose:** Stackplan turns module assessment screenshots into a simple, editable AI-generated to-do list that students can work through and return to.

**Most valuable outcome:** a student can identify a relevant suggested action, understand which assessment it supports, adapt or dismiss it, and mark it done without navigating several screens.

| Information class | Treatment |
| --- | --- |
| Extracted assessment facts | Names, weights and teaching weeks remain source interpretations until checked; tentative source wording remains tentative. |
| Deterministic rules | Week placement, record relationships and input validation constrain output; they do not prove extraction accuracy or task usefulness. |
| AI-generated tasks | Label the list “Suggested tasks from your assessments.” Tasks propose actions, not required work, verified deadlines or complete coverage of the trimester. |
| User information | Task edits, completion, dismissal and assessment corrections are explicit user inputs and must persist independently of AI generation. |
| Unsupported claims | No accurate effort estimates, personalised availability, optimal priority, improved grades or guaranteed coverage. A checked task does not prove an assessment was submitted or mastered. |

The current implementation can generate suggestions but cannot yet deliver the complete editable, persistent to-do experience. Product copy must match each delivered slice.

## 4. Priority problems

| Priority | Problem | Required outcome |
| --- | --- | --- |
| P0 | No persistent per-task state; regeneration/reload could erase the user's work. | Stable task IDs, saved completion/edits and revision-safe writes before interactive checkboxes ship. |
| P0 | Generated instructions can be mistaken for assessment facts. | Link suggestions to their assessment, distinguish suggested action from recorded assessment timing, remove hours and asserted priorities. |
| P0 | Extraction errors have no repair path. | Correct assessment facts without re-uploading; dependent tasks become visibly stale rather than silently changing. |
| P1 | Too many competing sections and no main action. | One task list with checkboxes; remove metrics, suggestion cards, decorative hero and weekly accordions. |
| P1 | Blind newest-recommendation selection can pair wrong tasks and facts. | Select an explicit active checklist bound to the shown assessment revision. |
| P1 | Partial failures and unknowns are easy to overlook. | Local context on affected rows; one concise message for list-wide failure or incomplete modules. |
| P1 | Long automatic generation blocks access to facts. | Finish extraction first; generate the checklist when requested; preserve facts and prior tasks on failure. |
| P2 | Upload limits disagree, credits add friction and mobile grid is too wide. | Align constraints, remove irrelevant inputs through contract changes, keep the grid secondary. |

P0 concerns reliable use, P1 concerns completing the core journey, and P2 concerns lower-priority friction. Visual hierarchy is central to this redesign, not a cosmetic finishing step.

## 5. Reduced scope

Keep a named trimester, module screenshots, assessment extraction and a single generated task list. Generate an initial checklist of at most 12 concise tasks across the supplied modules, using the existing checklist generator as the starting point. Do not manufacture one task for every week or fill an arbitrary hours budget. The cap limits initial output; it is not a claim that 12 tasks cover the term.

Include persistent check/uncheck, inline task-title editing, removal with immediate undo, a collapsed Done section, and links to the supporting assessment. Use one optional module filter. No kanban board, drag-and-drop priority, custom tags, subtasks, productivity score or progress chart.

Retain a secondary assessment view for checking and correcting extraction, unknowns, scope and partial coverage. Its Week overview is optional. Use original local images during the current upload session when available; permanent image storage remains deferred.

Generation is requested once after the student checks the extracted list. Returning to the project never calls AI automatically. Replacing a generated list is explicit and cannot silently discard completed, edited or removed tasks. Do not introduce automatic ongoing task generation.

Remove the full trimester revision-plan report, AI hours, priority labels, summary/highlight cards, workload/capacity statistics and recommendation-history navigation. This changes how generated advice is used; it does not remove AI-generated tasks.

## 6. Revised user journey

### A. Upload

- **Single purpose:** provide assessment material for one trimester.
- **Primary information:** compact title, trimester name, module titles, selected screenshots and actual format/size limits.
- **Primary action:** “Extract assessments.”
- **Secondary actions:** add/remove module or file, preview selected image, open a saved trimester.
- **Empty state:** one module row; short instruction to include all relevant pages.
- **Uncertain/partial state:** partial sources are allowed, with no promise of complete coverage.
- **Failure state:** field-specific errors; preserve entered metadata and selected files while the page remains open. Duplicate name offers rename or opening the existing project.
- **Must not appear:** decorative stack, oversized hero, credit input once omission is supported, productivity promises or a long onboarding wizard.

### B. Processing state

- **Single purpose:** explain the pending operation.
- **Primary information:** “Reading assessments” or “Generating suggested tasks,” according to the actual request. No fabricated percentage or ETA.
- **Primary action:** none while the request is pending; prevent duplicate submission.
- **Secondary actions:** assessment reference stays accessible during task generation where the UI can preserve it; do not promise unsupported background execution.
- **Empty state:** stay on the originating screen until a request starts.
- **Uncertain/partial state:** report only outcomes returned by the API; do not simulate per-module progress.
- **Failure state:** extraction failure preserves upload inputs; generation failure preserves assessments and any previous list, with Retry for generation alone. After connection loss, check saved state before resubmitting.
- **Must not appear:** a fake progress bar, automatic regeneration loop or suggestion to re-upload screenshots because advice generation failed.

### C. Assessment review and reference

- **Single purpose:** check the facts used to generate suggestions.
- **Primary information:** all-module assessment list with name, week/range and scoped weight; short material uncertainty labels. No timetable above it.
- **Primary action:** during initial setup, “Generate to-do list” after explicit acknowledgement that the visible extraction has been checked. Unknown values may remain; acknowledgement does not make them known. On return, Back to to-do.
- **Secondary actions:** correct a row, add omitted assessment, remove false row, optional module filter, expand source details, optional Week overview.
- **Empty state:** “No assessments extracted”; allow correction/manual entry or return to upload. Do not generate tasks without usable assessment facts.
- **Uncertain/partial state:** show missing module names and relevant coverage/timing limitations; generation may use usable assessments, but cannot claim to cover failed modules.
- **Failure state:** preserve unsaved corrections; distinguish current draft from saved revision. Conflicting save asks the user to reconcile while retaining their input.
- **Must not appear:** workload scores, credit-weight priorities, a separate review dashboard or a mandatory invented date.

### D. To do — main screen after generation and on return

- **Single purpose:** work through the saved suggested actions.
- **Primary information:** compact trimester title, “To do,” one short AI-suggestion label, and unchecked task rows across modules. Each row shows checkbox, verb-led title and module. Assessment timing appears as “Assessment: Week 8” when known, never as the task's invented due date.
- **Primary action:** check or uncheck a task. A row opens its supporting assessment/details in place.
- **Secondary actions:** edit title, remove with undo, one module filter, collapsed Done section, Assessments link. Regenerate is secondary and deliberate, not a large competing CTA.
- **Empty state:** distinguish “No list generated” (Generate), “No useful suggestions returned” (inspect assessments or retry), “All tasks done” (view Done), and “No tasks match this module” (clear filter). Do not automatically refill an empty list.
- **Uncertain/partial state:** short unknown/tentative label on the relevant row; one concise banner only for missing modules or stale source revision. Tasks with no known assessment week stay unscheduled, not overdue.
- **Failure state:** failed completion/edit save retains the previous committed state and clearly marks the pending change unsaved; allow retry or undo. Loading failure does not look like an empty list.
- **Must not appear:** suggestion cards above the list, summary paragraphs, active-week/action/hour metrics, priority badges, weekly accordions, a 14-column grid or a decorative hero.

### E. Inline edit and replacement states

- **Single purpose:** modify a task or deliberately replace generated suggestions without losing user work.
- **Primary information:** selected title with assessment context; for replacement, explain the effect on the active list before any destructive change.
- **Primary action:** Save for a task edit; Generate replacement for an explicit regeneration request, followed by Use new suggestions after preview.
- **Secondary actions:** Cancel, undo removal, keep existing list. Expanded assessment details link to correction without changing the task's source silently.
- **Empty state:** reject blank task titles; a replacement with no valid tasks leaves the existing list active.
- **Uncertain/partial state:** replacement items are suggestions based on the current assessment revision. Show affected stale source relationships locally.
- **Failure state:** keep existing list and all completion/edit state; preserve local edit on conflict. Never mark an unsuccessful replacement active.
- **Must not appear:** model rationale essays, invisible completion resets, automatic matching of tasks solely by title, or a general recommendation-history dashboard.

## 7. Information architecture

```text
Start / open trimester
└── Upload → extract → check assessments → generate
Saved trimester
├── To do [default]
│   ├── Task details / inline edit
│   ├── Done [collapsed]
│   └── Replace suggestions [secondary, deliberate]
└── Assessments [reference and correction]
    └── Week overview [secondary]
```

Use a compact trimester picker and New trimester. Remove the three-step demo strip, repeated eyebrow labels and “View study plan” as the dominant assessment-screen destination. Existing plan links map to To do; assessment links remain usable. When there is no active list, open the saved assessment review and offer generation rather than generating on page load.

## 8. Functional and truthfulness rules

1. **Task content:** generate concrete verb-led suggestions tied to existing assessment IDs and modules. Do not invent chapters, topics, resources, deliverables or rubrics absent from the input. Generic habits with no assessment relationship are excluded from this iteration. Repetitive preparation is consolidated where the relationship remains clear. Prompt rules alone do not prove semantic fidelity; students can edit or remove suggestions.
2. **Generation contract:** start from the existing work-checklist pathway, capped at 12 initial tasks. A future task contract must remove mandatory hours, priority, summary and week-allocation fields. Merely hiding them leaves unnecessary model work and validation dependencies. Keep assessment-reference checks and source revision binding. A user-edited task need not meet AI wording restrictions but must remain non-empty and safely rendered.
3. **Timing:** display recorded assessment timing as context, not a generated task deadline. Do not schedule preparation into numbered weeks in this iteration. Unknowns remain unknown; raw dates do not become teaching weeks without a calendar anchor. No current-week, overdue or due-today labels without the necessary dates.
4. **Completion:** only user action checks a task. Task done does not mean assessment complete, submitted, passed or understood. Completing one preparation task never checks other tasks or modifies assessment facts. Completion is not extraction review. Uncheck is always available from Done.
5. **Identity and persistence:** allocate durable task IDs when a generated list is stored. Task title/index is not identity. Persist task edits, done state, removal and active-list selection independently of the immutable original generated payload. Recommendation candidate/accepted/dismissed status is not per-task state.
6. **Replacement:** generation creates a candidate, never overwrites the active list. Replacement confirmation preserves completed and user-edited tasks and their identities; only unchanged open generated suggestions are replaced. New candidate tasks receive new IDs and remain unchecked. Retain removed-task records; suppress an exact repeat for the same assessment and normalized original title. Do not claim semantic deduplication of paraphrases. If preserved tasks overlap new suggestions, make that visible in the replacement preview and allow excluding the new duplicate. An empty/failed candidate leaves the previous list active. Old unselected records remain stored without a history screen.
7. **Stale sources:** a list binds to the exact assessment revision used to generate it, not simply newest recommendation time. An assessment correction makes dependent suggestions stale; preserve completion and edits, flag affected tasks, and offer deliberate replacement. If an assessment is removed, keep its tasks with a source-removed label until the user removes them; never silently relink them.
8. **Correction:** preserve original extracted values and stable assessment IDs when editing; manual additions get new IDs. Rebuild the deterministic assessment overview from corrected records, without another AI call or prototype expansion. User review applies to current facts and is invalidated when those facts change. Legacy records are unreviewed by default.
9. **Unknowns, ranges and groups:** retain unknown weight/date; never assign zero, Week 1 or equal divisions. Active ranges are not repeated deadlines; topic coverage is not an activity window. Group totals are scoped parent information, not individual assessment weights or task counts. Validate corrected percentages as finite 0–100 and preserve unknown scope. Reject broken group relationships rather than guessing.
10. **Recess and ambiguity:** current Week 7 exclusion for ranges/recurrence is an application convention. Explicit Week 7 events remain visible. Ambiguous list-like ranges or conflicting recess evidence stay flagged and unplaced until clarified; no unexplained gap. The task list makes no promise that recess is free.
11. **Coverage:** “Based on supplied screenshots” is the baseline. AI `appears_complete`, summed weights of 100% or reviewed visible rows do not prove complete source coverage. Tentative source wording remains visible. Missing modules remain named after reload; valid modules remain usable. Do not generate suggestions for a failed module.
12. **Atomic writes:** saved means committed. Every assessment or task write includes its base revision; compare and save atomically, rejecting stale writes. Late extraction/generation cannot replace newer user changes. Separate source revision from task-state revision so checking a task does not invalidate its assessment basis. Save failures retain drafts and previous committed data.
13. **Safe display:** escape user and AI names, titles, notes, wording and errors; do not execute HTML, Markdown links or scripts from output. Validate identifiers and enums. Keep visible keyboard focus and announce errors; colour alone cannot indicate uncertainty or completion.
14. **Sources:** current uploads are temporary and not a durable evidence library. Show local preview only when available. A saved project must explicitly say its original image is unavailable rather than providing a broken source link.
15. **Cost and waiting:** extraction currently uses three calls per relevant successful module and advice adds another, absent retries. Retaining generation retains its cost. Removing redundant fields and limiting tasks may reduce output, but no speed or price savings are promised without measurement. No model calls on reopen, checkbox, edit, dismissal or assessment correction; explicit generation/replacement alone requests tasks.

## 9. UI reduction plan

| Action | Exact elements | Intended result |
| --- | --- | --- |
| Remove | `planSuggestions` cards; Active weeks, Planned time and Actions metrics; priority/hour pills; weekly focus headings and accordions; summary fallback. | The task rows receive attention immediately. |
| Replace | Report-style `planView` / `planResult` layout with To do rows, checkbox, title, module and expandable assessment context. | Preserve useful generated actions in an actionable list. |
| Combine | Suggested actions across weekly buckets into one list; flexible/unknown-date items remain visible without a separate advice page. | No hunting through several week accordions. |
| Demote | `timeline` to optional Week overview; `moduleBrowser` to assessment reference; weights, raw wording and source notes inside details. | Information remains accessible without dominating the main screen. |
| Remove | Decorative stack, oversized working-screen hero, repeated eyebrow headings, three-step demo strip and duplicated explanatory text. | List or form begins directly under a compact heading. |
| Retain | Named trimester, picker, multi-image upload, source association, safe text and unknown labels. | Preserve core input and context. |
| Add | Durable check/uncheck, inline edit, removal with undo, collapsed Done and reliable save state. | A real to-do workflow rather than a static generated report. |
| Add | Assessment correction, source-revision binding and protected list replacement. | Errors can be repaired without losing task state. |
| Reduce | Credits and importance ranking: remove after relevant contracts permit omission; retain legacy metadata. | No irrelevant setup or hidden priority ordering. |

Immediately visible: checkbox, task title, module and concise relevant assessment timing/uncertainty. Secondary: supporting assessment, weight, original wording, edit/remove actions, generation details and revision timestamp. Label the list's AI origin once; do not repeat an AI badge on every row.

Use one column of text rows and separators, not an elevated card for every task. Default to all modules, ordered by linked assessment week/start week with stable module/name/task-ID tie-breaks; unknown timing follows in an unnumbered group. This is a presentation order, not claimed urgency. Done is collapsed below open tasks. No additional priority/grouping/sorting controls in this iteration. Preserve scroll position when opening details and keyboard focus after actions. Use the existing muted palette if desired; changing colours is less important than removing sections.

## 10. Explicit non-goals

No calendar integrations, reminders, grade prediction, risk scoring, daily scheduling, optimisation, time budgets, effort estimates, progress charts, streaks, AI chat, resource recommendation, kanban, subtasks, collaborative assignment, automatic semester-long task replenishment or LMS submission tracking.

Defer durable image storage, crop-level attribution, account rollout, background job queues, streamed progress, configurable calendars, automatic cross-run assessment merge and intelligent task-state transfer across paraphrased regenerated tasks. Do not market existing shared-project storage as a private personal account. A simple student-controlled done state is in scope; a productivity analytics system is not.

## 11. Implementation feasibility

| Change | Existing boundaries and required work | Classification |
| --- | --- | --- |
| Remove clutter and flatten actions | Frontend `planView`, `planResult`, `planSuggestions`, model helpers, template and styles; legacy plan data can supply titles and assessment links for a transitional read-only list. Include existing flexible items rather than silently dropping them. | **Removal or simplification** |
| Short checklist generation | Existing `ChecklistGenerator`, recommendation API and validator provide a foundation. Future prompt/output/domain contract changes remove hours, priority, summaries and imposed task weeks while keeping source links. Current validators require those removed fields. | **Moderate extension** |
| Separate extraction and generation | `PlanningService._process` currently calls advice automatically; return/save assessments first. Existing recommendations POST can generate afterwards, but must use the current corrected revision and select the new task contract. No job queue required. | **Moderate extension** across workflow and contracts |
| Task completion/edit/removal | No task-state API or persistent task IDs exist. Add commands, application validation, durable identities and repository records. Current recommendation status is only whole-record acceptance. | **Moderate extension** |
| Safe replacement and active list | Existing input hash and recommendation records help retain generation evidence. Add explicit active-list binding, task-state preservation, candidate preview/selection and atomic revision checks. Newest timestamp selection is insufficient. | **Moderate extension** |
| Assessment corrections | New API command, application service, corrected-record validation, preserved identity/provenance, revision storage and overview rebuild. Avoid renormalizing expanded prototypes. | **Moderate extension** |
| Durable saved revisions | PostgreSQL JSONB can store new metadata but does not provide concurrency control automatically. Design source/task revisions and transactional compare-and-save, with backward-compatible legacy reads. Physical schema changes may be needed later. | **Moderate extension** |
| Coverage display and upload alignment | Existing metadata supports coverage and source wording; frontend labels and accepted-file constraints can reuse it. Persist requested module identities/outcomes for reliable partial-state reloads. | **Small extension** for display; **Moderate extension** for outcome persistence |
| Remove credits/ranking | Submission validator, module/domain serialization and schedule builder assume credits. Allow absence without inventing a substitute; remove rank-driven ordering and preserve historical fields. | **Moderate extension** |
| Durable source images or background processing | Temporary files and synchronous request lifecycle do not support these capabilities. Require new storage/access/lifecycle or job infrastructure. | **Major architectural work — defer** |

Do not implement completion solely in browser memory/local storage, overload pipeline status as user completion, or rewrite immutable generated evidence when a user edits a task. Existing fake-provider tests validate shapes and boundaries; they do not establish whether students find tasks useful. This task changes only the Markdown specification; all implementation, prompt, schema and test changes above are future work.

## 12. Acceptance criteria

These are future observable gates, not checks claimed to have run in this design audit.

| ID | Observable criterion |
| --- | --- |
| AC01 | At 390 × 844 and 1440 × 900, a non-empty active list shows its first task in the initial viewport. No hero, metric cards, suggestion cards or timetable precedes it. |
| AC02 | Tasks from all modules appear in one default list, with checkbox, title and module. One module filter narrows that same list. Details open without page navigation or loss of scroll position. |
| AC03 | No AI hours, high/medium/low priority badges, weekly focus accordions or workload claims appear. AI origin is labelled once for the list. |
| AC04 | Extraction returns saved facts before task generation is requested. Initial generation returns at most 12 valid assessment-linked suggestions; it is not required to fill every week or cover every assessment. |
| AC05 | Saving a checkbox, task edit/removal, assessment correction or reopening a project makes zero model calls. Only explicit generation/replacement requests call the task generator. |
| AC06 | Check, reload and reopen retains done state. Uncheck restores the same task ID and title to the open list. Neither operation marks an assessment submitted or other tasks complete. |
| AC07 | Editing a task title persists under the same ID. Removing it offers immediate undo and remains removed after reload. Blank titles are rejected without losing the draft. |
| AC08 | Completing all tasks shows the distinct all-done state and a way to reopen Done; no automatic generation occurs. Filtered-empty and generation-empty states have different explanations. |
| AC09 | Failed checkbox/edit saves never appear committed. Previous saved values and pending input remain recoverable; stale writes are rejected without silently overwriting newer state. |
| AC10 | Generation failure preserves assessments and any active list. Retry requests generation alone and does not require screenshots again. |
| AC11 | Replacement is previewed before activation. Completed and user-edited tasks retain their identities/state; unchanged open suggestions can be replaced only after explicit confirmation. An empty candidate does not replace the active list. |
| AC12 | A removed task's exact original title for the same assessment is not silently reintroduced during replacement. Potential overlap with preserved tasks is visible in preview; no completion transfers by title/index. |
| AC13 | Correcting assessment timing changes the factual reference and flags dependent tasks as stale, without erasing task edits/completion or generating new tasks automatically. Active list retains its original source revision binding. |
| AC14 | Unknown assessment timing remains unknown in list and details, without invented task deadline, overdue state or Week 1 default. Tentative timing remains qualified. |
| AC15 | A 30% group weight for three quizzes remains a group total, not three 10% or 30% item weights. Group headers are not independent assessment events. |
| AC16 | An activity range is distinguishable from separate due events; topic coverage alone does not create scheduled activity. Ambiguous ranges stay flagged and unplaced until clarified. Explicit Week 7 events remain visible. |
| AC17 | Partial coverage and missing module names survive reload; a successful partial response never becomes a claim of complete trimester coverage. |
| AC18 | Corrected facts persist with stable IDs, original extracted values and review state. Changes invalidate prior review. Invalid percentages, weeks or parent links are rejected while unknown values remain valid. |
| AC19 | User/AI/script-like text renders literally in task titles, source details and errors. Keyboard users can check, edit, cancel, undo and navigate Done with visible focus. |
| AC20 | Supported PNG/JPEG formats and real limits are stated before upload. WebP is not offered as supported. Files/metadata survive recoverable failure while the form remains open. |
| AC21 | Legacy recommendation payloads remain readable without deleting them. Only an explicit list tied to the right source revision is active; newest recommendation time alone cannot select it. |
| AC22 | Original-image access is shown only while the image is available; later visits state its absence. Processing has no invented ETA/progress or background-resume promise. |

## 13. Delivery sequence

1. **Remove clutter before adding features.** Strip metric and suggestion cards, hours, priority badges, weekly accordions, decorative stack and repeated headings. Flatten existing generated actions into a readable list, include flexible items, and demote timetable/details. Keep it explicitly read-only until persistence ships; no nonfunctional checkboxes. Preserve saved data. This first slice retains generation and changes the presentation.
2. **Deliver a real to-do interaction.** Add durable task IDs, task-state commands, active-list binding, atomic save/conflict handling, then check/uncheck, edit, remove/undo and Done. Gate on persistence and failure cases, not just the appearance of checkboxes.
3. **Reduce generation scope and waiting.** Introduce the short checklist contract without hours/priorities/summary fields. Separate extraction from requested generation, keep assessment facts available on generation failure, and prevent model calls during ordinary list use. Retain legacy readers while migrating active lists deliberately.
4. **Complete correction and safe replacement.** Add assessment corrections and source/task revisions, stale labels, candidate preview and protected replacement. Persist partial module outcomes, align input constraints and remove credit/ranking dependencies. The full repeat-use loop is not complete until mistakes and regeneration are recoverable.
5. **Validate the interface and generated actions.** Observe students locating a task, inspecting its source, editing/removing it, marking it done and returning later. Measure first-action time, unnecessary navigation, suggestion edits/dismissals, source errors and extraction/generation latency. Compare the simplified list with the current report layout. Do not expand into more planning tools unless the list itself helps.

All slices require implementation approval. Existing tests will need to change to the new contracts; do not retain hours or automatic revision-plan assertions merely to preserve old tests. Use varied annotated screenshots to evaluate extraction separately from whether generated tasks are useful.

## 14. Final recommendation

**Recommended direction:** retain AI-generated study actions, presented as a short editable to-do list. Make this the main screen after setup and on return. Keep assessment facts close enough to inspect without competing with the list.

**First implementation slice:** remove the report layout and flatten the existing generated actions into one readable list. Do not add checkboxes until their state can be saved reliably.

**Remove first:** suggestion/summary cards, hours, priority badges, statistics, weekly accordions, oversized headings and decorative sections. Demote the timetable.

**Most valuable missing functionality:** persistent completion, task editing/removal and a correction path for the assessment information that generated the task. Safe replacement must preserve the student's work.

**Validate before expanding:** whether students understand what to do immediately, find the generated actions specific enough to act on, distinguish suggestions from assessment requirements, can dismiss irrelevant work, and return to a list that accurately remembers their actions. The product succeeds through useful tasks and low-friction interaction, not through the number of generated sections or metrics.

Implementation remains unapproved. This document is the design deliverable only.
