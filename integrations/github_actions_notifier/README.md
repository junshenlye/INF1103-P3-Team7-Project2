# Telegram PR and CI notifier

This optional GitHub Actions integration watches this repository and sends concise Telegram group notifications when pull requests, reviews, issues, CodeRabbit top-level comments, or completed CI runs change. It runs without a webhook server, always-on machine, or third-party Python packages.

## Enable it

1. Create a Telegram bot with BotFather and add it to the target group.
2. In this repository, open **Settings → Secrets and variables → Actions** and add:
   - `TELEGRAM_BOT_TOKEN`: the private bot token.
   - `TELEGRAM_CHAT_ID`: the group's negative chat ID.
3. Enable the **Telegram PR and CI notifier** workflow in Actions. It runs on its schedule, on manual dispatch, and when notifier code changes on `main`.
4. The first successful run verifies the bot and group, then records a silent baseline. Later runs send notifications for new or changed records. A connection-test message is sent only when explicitly selected during manual dispatch.

No secrets are required to run the unit tests. The notification step is skipped until both Telegram secrets are configured. Never put tokens in source files, workflow YAML, committed `.env` files, or logs.

The workflow's `GITHUB_TOKEN` is read-only and limited to repository contents, pull requests, issues, and Actions metadata. If this repository becomes private or GitHub's token cannot read the source, configure optional `SOURCE_GITHUB_TOKEN` as a fine-grained token with read-only access to this repository's **Pull requests**, **Issues**, and **Actions**.

## What it watches

- New pull requests and changes to open/draft/closed/merged state, title, head commit, assignees, and requested reviewers.
- Submitted PR reviews and changes in review state.
- New or edited CodeRabbit top-level PR comments, with links to the comments.
- New or edited GitHub Issues, including state, title, and assignees.
- Completed CI workflow runs and completed re-runs.

It compares snapshots, not a full event stream. Multiple changes between checks can be combined into the latest state. It queries all open PRs, recently updated closed PRs, and CI runs created in the last seven days. Inline review comments and individual CI jobs are not reported; review bodies are not forwarded.

## Schedule and delivery limits

The workflow checks at minutes 7, 17, 27, 37, 47, and 57 each hour. GitHub may delay or skip scheduled runs, and public-repository scheduled workflows are disabled after 60 days without repository activity. This is a best-effort team alert, not an immediate-delivery or guaranteed audit service.

Notification state is stored in the Actions cache under `integrations/github_actions_notifier/.state`. It contains public repository metadata, never credentials. Runs are serialized. Each successful send is recorded before the next message, but a crash after sending and before saving, or cache eviction, can cause duplicates or reset the watcher to a silent baseline. A cache reset may miss changes around the reset.

The workflow never checks out or executes PR code or artifacts. Telegram messages are plain text. API errors are deliberately sanitized because Telegram API URLs contain the bot token.

To pause alerts, disable the workflow in Actions. To reset the baseline, delete the workflow's `pr-watch-v1-*` caches. To change the source repository, update `SOURCE_REPOSITORY` in the workflow and change the cache prefix so old state cannot be reused.

## Local checks

Run from this directory:

```sh
python3 -m unittest -v
python3 watch.py --dry-run
```

The tests mock all remote services. Dry run reads the public source only; it sends no messages and saves no state. Python 3.9+ is supported.
