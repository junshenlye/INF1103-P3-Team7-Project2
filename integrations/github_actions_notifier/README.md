# Team PR Watch

A small, scheduled GitHub Actions integration that monitors this repository and sends Telegram notifications when project activity changes. It runs on GitHub-hosted runners and uses only Python's standard library; no always-on server or third-party Python packages are required.

## Configure

1. Create a Telegram bot with BotFather and add it to the team group with permission to send messages.
2. In **Settings → Secrets and variables → Actions**, add repository secrets:
   - `TELEGRAM_BOT_TOKEN`: the bot token.
   - `TELEGRAM_CHAT_ID`: the group's negative chat ID.
3. Open **Actions → Team PR Watch → Run workflow** to run a check. Select the optional connection-test input only when you want one test message sent to the group.

The workflow checks approximately every ten minutes. GitHub may delay scheduled runs, so notifications are not guaranteed to be immediate. If the Telegram secrets are not configured, scheduled checks and pushes still run the unit tests and safely skip notification delivery.

## Notifications

The watcher detects new or changed pull requests (including draft, closed and merged state, title, head commit, assignees and requested reviewers), submitted PR reviews, CodeRabbit top-level PR comments, changed Issues, and completed GitHub Actions workflow runs.

The first successful check stores a silent baseline instead of sending historical activity. Subsequent checks notify on new or changed records. The watcher retains recent state between runs using the Actions cache. Several changes between checks may be combined into the latest snapshot; this is not a complete event audit or guaranteed-delivery service.

## Security and limitations

- The workflow uses a read-only `GITHUB_TOKEN` for this repository and does not check out or execute pull-request code.
- Telegram credentials are read only from Actions secrets. API errors are sanitized so bot-token URLs and response bodies are not printed.
- Notification messages are plain text. Inline review comments and individual jobs inside a workflow run are not reported.
- Cache eviction resets the watcher to a silent baseline and may miss changes around that reset. A failure after sending but before saving state can cause a duplicate notification.
- To pause notifications, disable the workflow in Actions. To change the monitored repository, update `SOURCE_REPOSITORY` in the workflow and reset the cache prefix.

## Local verification

From this directory:

```sh
python3 -m unittest -v
python3 watch.py --dry-run
```

The unit tests mock GitHub and Telegram requests. Dry run reads the configured source but sends no messages and does not save state. Python 3.9+ is supported.
