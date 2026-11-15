# Placeholder import

This series imports completed work from `junshenlye/Placeholder`, commit
`1b4bc577d0e74dcf70764568f7ca3e9148c0ec00`, onto assignment repository commit
`ae92eaf3e1b5b27ed86f31cb1f94fa85a4bb7f8f`.

The ten pull requests are ordered for review and should be merged in order:

1. Send replacement document bytes without JSON encoding.
2. Inspect partial results and individual source documents.
3. Improve the responsive assessment schedule and module colours.
4. Update processing progress, schedule navigation and recovery actions.
5. Configure worker concurrency and restart behaviour.
6. Consolidate the backend into the 17-class manager architecture.
7. Verify persistence, recovery and browser-to-database behaviour.
8. Document and verify UML, ownership and lifecycle transitions.
9. Remove superseded guides and the loading-only demo.
10. Retain notification integration checks in the migrated CI workflow.

Each branch builds on the preceding branch. These are imports of existing work;
their order represents review dependencies, not when the features were originally developed.

Assignment-only Telegram integrations, their notification workflow, `.editorconfig`,
the existing API and progress-event unit tests, and the applied migration SQL are
retained. The backend migration replaces the obsolete helper classes and their
tests together because the manager interfaces and ownership rules change together.
The test runner uses an isolated disposable PostgreSQL database and deterministic
providers; live API credentials are not needed.
