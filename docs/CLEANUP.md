# Cleanup candidates for the Feature #1 rewrite

Tests and grader material have been removed; replacement testing is deferred.
The items below are review candidates, not confirmed dead code. Production
behavior has not been removed in this cleanup.

| Candidate | Why review it | Suggested decision |
| --- | --- | --- |
| `experiments/document_pipeline/` | Separate document extraction stack, UI, server and Docker deployment alongside the main app. | Choose which implementation will own Feature #1, then merge useful parts or remove the prototype. |
| `docs/PRODUCT_SIMPLIFICATION.md` | Long historical proposal with old evidence and a product direction that may change. | Extract current requirements after deciding the rewrite scope; discard obsolete sections. |
| `docs/images/` and README previews | Screenshots describe the current study planner and may become stale. | Replace or remove when the new UI is settled. |
| `src/ai_manager/recommendation_generator.py`, `src/logic_manager/recommendation_validator.py`, `src/domain/study_plan.py` | Advice and study-plan behavior may be outside the revised Feature #1. Currently used by the application. | Confirm scope before removing; update pipeline, frontend and persistence together. |
| `helpers/docker_cli.py`, `src/main.py`, Compose CLI service | Additional entry point alongside browser/API. | Keep if command-line processing is required; otherwise simplify as one coordinated change. |
| `requirements.txt`, `frontend/requirements.txt` | Long dependency lists include transitive packages. | Review direct dependencies and locking strategy; do not drop dependencies solely because imports are indirect. |
| `.venv/`, `.ruff_cache/`, `__pycache__/`, `.DS_Store` | Local generated files, not application source. | Optional disk cleanup; recreating the environment requires reinstalling dependencies. |

Keep `.env`, database storage, schema and deployment launchers unless separately
changing those workflows. Database health checks are runtime readiness checks.
