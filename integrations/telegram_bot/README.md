# Telegram PR tracker

An independent Python 3.9+ service with no additional packages. It does not change the Stackplan app, create issues, merge PRs, or post code to Telegram.

## Run commands on this Mac

With the private `.env` configured, run from the project root:

```sh
python3 integrations/telegram_bot/install_macos.py
```

This copies the listener and private configuration to `~/Library/Application Support/TeamPRBot`, starts it in the background, and installs a per-user login service. No administrator account, HTTP port, public URL, or GitHub webhook is needed for this mode. The scheduled watcher in `junshenlye/team-pr-watch-7f3c9a` continues to send GitHub alerts, while this Mac handles `/prs`, `/tasks`, and `/help` in the configured group. Only one command listener should run for this bot token.

The Mac must be awake, online, and logged in for immediate command replies. Closing the chat or terminal does not stop the login service. Updating files in this project does not change the installed copy until the installer is run again. The `.env` in the runtime directory is private to your user. `stdout.log` records startup and successful command names; `stderr.log` contains failures. `state.sqlite3` stores the Telegram offset and last successful polling/command times.

```sh
python3 integrations/telegram_bot/install_macos.py --status
python3 integrations/telegram_bot/install_macos.py --stop
```

Stopping also disables next-login startup; configuration/state are retained. Re-run the installer to start and enable it again. For a foreground session instead, use `python3 integrations/telegram_bot/bot.py --commands-only`.

## Connect the group

1. Copy `.env.example` to `.env` in this folder, unless the private file already exists. Keep it private and excluded from Git. Set `TELEGRAM_BOT_TOKEN` from BotFather and generate a long random `GITHUB_WEBHOOK_SECRET` (the prepared local file already has one).
2. Add the bot to the desired Telegram group with permission to send messages. Admin rights and disabling privacy mode are unnecessary.
3. Run `python3 integrations/telegram_bot/bot.py --discover` from the repository root. It prints the bot username without exposing the token.
4. Send `/setup@YourBotUsername` in the group. Run discovery again if the first attempt timed out. It prints matching group IDs locally and sends no messages. Select the intended group and put its negative ID in `TELEGRAM_CHAT_ID`. Invite links cannot substitute for this ID. Discovery does not automatically select a group.
5. Run `python3 integrations/telegram_bot/bot.py`. Only run one instance per bot token. It uses Telegram long polling; an existing Telegram webhook must be removed before running it.

## Connect GitHub

Keep the service running on a computer/server. Expose port 8088 through a trusted HTTPS reverse proxy or tunnel. Put the service behind that proxy; the Python HTTP listener is not an internet-facing TLS server. No host or tunnel is provisioned by this integration.

In the repository's **Settings → Webhooks → Add webhook**:

- Payload URL: `https://YOUR-HOST/github`
- Content type: `application/json`
- Secret: the private `GITHUB_WEBHOOK_SECRET` value
- Keep SSL verification enabled
- Select **Pull requests**, **Pull request reviews**, **Issue comments**, **Issues**, and **Workflow runs**

GitHub sends signed events; the service verifies the signature and configured repository before forwarding. Delivery IDs are retained in local SQLite for 30 days to suppress ordinary retries. A crash after Telegram accepts a message but before the local receipt is saved can still duplicate it. Failed sends return HTTP 503: inspect GitHub's Recent Deliveries and manually redeliver failures; do not assume automatic retries. Preserve `state.sqlite3` across restarts.

Notifications cover PR opening/reopening, closing/merging, ready-for-review, review requests, submitted reviews, new CodeRabbit top-level PR comments, task opening/assignment/closing, and completed GitHub Actions workflows. CodeRabbit comments edited in place and inline review-comment events are not forwarded. CI messages describe individual workflows, not an aggregate merge-readiness verdict.

Group commands:

- `/prs` — first 20 open PRs with links and assignees
- `/tasks` — first 20 open Issues with links and assignees (filters the first 100 Issues API results)
- `/help` — command list

Use `/prs@YourBotUsername` if Telegram needs an explicit bot mention. Commands from other chats are ignored. Public repository reads work without `GITHUB_TOKEN`, subject to GitHub's shared unauthenticated rate limit. An optional fine-grained token only needs read access to **Issues** and **Pull requests** for this repository. No GitHub write token is required for notifications.

## Divide work

Create one GitHub Issue per small deliverable, assign one owner, and include acceptance criteria, dependencies, and a test/checklist. Use one branch and PR per Issue. Put `Closes #123` in the PR description to link completion on merge into the default branch. Team username mappings and requirements are still needed before implementing personal task commands or creating a project-specific backlog.

## Verify

```sh
cd integrations/telegram_bot
python3 -m unittest -v
```

Tests mock Telegram/GitHub and verify signed webhook handling, duplicate suppression, failed-delivery retry, repository/group restrictions, CodeRabbit filtering, and task listing. `/health` checks the HTTP listener only, not remote API availability. Secrets are never included in error output. Rotate the bot token in BotFather if exposed, then update the private `.env` and restart.
