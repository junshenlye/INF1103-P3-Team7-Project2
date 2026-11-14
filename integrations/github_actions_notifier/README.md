# Team PR Watch

An optional GitHub Actions integration that monitors this repository and sends team updates to a Telegram group. It runs entirely on GitHub-hosted runners and requires no webhook server or additional Python packages.

## Setup

1. Add the following repository secrets under **Settings → Secrets and variables → Actions**:
   - `TELEGRAM_BOT_TOKEN`: the Telegram bot token.
   - `TELEGRAM_CHAT_ID`: the negative chat ID of the intended Telegram group.
2. Ensure the bot is a member of that group and can send messages.
3. Open **Actions → Team PR Watch → Run workflow**. Optionally select **Send one Telegram connection-test message**. The first successful run records a baseline without sending historical notifications; later runs report changes.
4. The scheduled workflow checks approximately every ten minutes. GitHub may delay or skip scheduled runs, so this is not an immediate-delivery service.

The automatic `GITHUB_TOKEN` reads this public repository. If the repository becomes private and the default token cannot read it, configure the optional `SOURCE_GITHUB_TOKEN` secret with read-only access to Pull requests, Issues and Actions.

## Notifications

- New pull requests and changes to their state, title, head commit, assignees or requested reviewers.
- Submitted pull request reviews.
- New or edited CodeRabbit top-level pull request comments.
- New or edited GitHub issues, including state, title and assignees.
- Completed CI workflow runs and completed re-runs.

The watcher compares snapshots. Multiple changes between checks can be combined into the latest state; this is not a complete event audit. Inline review comments and individual CI jobs are not reported. PR review bodies are not forwarded.

## State and security

Notification state is stored in `.state/watch.json` under this integration directory and carried between runs using Actions cache. It contains repository metadata, never bot tokens. Runs are serialized. Successfully sent notifications are recorded before the next message; a crash after sending but before saving can still cause duplicates. Cache eviction resets the watcher to a silent baseline and may miss changes around that reset.

The workflow runs on a schedule, manual dispatch, or changes to its own files on `main`. It does not check out or execute pull request code. Telegram messages are plain text. API errors are sanitized so bot tokens are not written to logs.

To pause notifications, disable **Team PR Watch** in Actions. To reset the baseline, delete the workflow's `team-pr-watch-v1-*` caches.

## Local checks

Run from this directory:

```sh
python3 -m unittest -v
python3 watch.py --dry-run
```

Tests mock remote services. Dry run reads the repository only; it sends no messages and does not save state. Python 3.9+ is supported. Never commit bot tokens or chat credentials.
