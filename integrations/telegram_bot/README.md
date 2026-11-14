# Telegram group command bot

An optional, standalone Python 3.12+ integration for querying this repository from a Telegram group and forwarding selected GitHub events. It uses only the Python standard library and does not change the Stackplan application or require application/provider credentials.

## Configure

1. Create a Telegram bot with BotFather and add it to the intended group. Give it permission to send messages; admin rights and disabling privacy mode are not required.
2. Copy `.env.example` to `.env` in this directory. Set `TELEGRAM_BOT_TOKEN` and `GITHUB_REPOSITORY`. Keep `.env` private; it is ignored by Git.
3. Discover the bot username and group ID without sending a message:

   ```sh
   python integrations/telegram_bot/bot.py --discover
   ```

   Send `/setup@YourBotUsername` in the group, then run discovery again. Copy the printed negative group ID into `TELEGRAM_CHAT_ID`.
4. Start the command listener:

   ```sh
   python integrations/telegram_bot/bot.py --commands-only
   ```

   Keep one listener running for this bot token. It uses Telegram long polling and stores its update offset in the local `state.sqlite3` file so restarts do not normally replay old commands. The host must remain online for immediate replies.

## Optional macOS login service

On macOS, install the command listener as a per-user LaunchAgent so it starts at login and restarts if it exits:

```sh
python3 integrations/telegram_bot/install_macos.py
```

The installer requires the private `integrations/telegram_bot/.env` file. It copies only `bot.py` and that configuration into `~/Library/Application Support/TeamPRBot`, with private directory and file permissions, and registers a LaunchAgent for the current user. It uses the Python interpreter running the installer. No administrator privileges or public HTTP endpoint are required for command polling.

Inspect or stop the service with:

```sh
python3 integrations/telegram_bot/install_macos.py --status
python3 integrations/telegram_bot/install_macos.py --stop
```

Stopping removes the login agent but preserves the installed configuration and SQLite state. Re-run the installer after updating the bot or its configuration. The Mac must be awake, online, and logged in for immediate command replies. Do not run a second polling listener for the same bot token.

## Group commands

- `/help` or `/start` — show the command list.
- `/prs` — list up to 20 open pull requests with links and assignees.
- `/tasks` — list up to 20 open GitHub Issues (pull requests are filtered out).
- Add `@YourBotUsername` to a command if Telegram needs an explicit bot mention.

Commands from chats other than the configured group are ignored. Public repository reads need no GitHub token; an optional fine-grained `GITHUB_TOKEN` only needs read access to Issues and Pull requests for this repository. No GitHub write permission is used.

## Optional immediate GitHub event notifications

To forward GitHub events as well as answer group commands, run the default server mode instead of `--commands-only`. Set a random `GITHUB_WEBHOOK_SECRET` of at least 32 characters and optionally `PORT` (default 8088). The service listens on `/github` and `/health`.

Expose it only through a trusted HTTPS reverse proxy or tunnel; the Python listener itself does not provide TLS. In GitHub **Settings → Webhooks**, add `https://YOUR-HOST/github`, choose JSON, use the same secret, keep SSL verification enabled, and subscribe to Pull requests, Pull request reviews, Issue comments, Issues, and Workflow runs.

The handler verifies GitHub's SHA-256 signature, checks the repository, limits request bodies, and stores successful delivery IDs in SQLite for 30 days. Failed Telegram sends return HTTP 503 so the delivery can be investigated and redelivered. A crash after Telegram accepts a message but before the delivery receipt is committed can still produce a duplicate. Only top-level CodeRabbit PR comments are forwarded; edited comments and inline review comments are not.

**Do not run two polling listeners for the same bot token.** A Telegram bot can use either long polling or a Telegram webhook; this integration uses long polling.

## Verify

```sh
python -m unittest discover -s integrations/telegram_bot -v
```

Tests mock Telegram and GitHub and cover group restrictions, command output, event formatting, signed webhook requests, duplicate delivery suppression, and retry after a failed send. Installer tests mock `launchctl` and filesystem paths; they do not install a real macOS service or contact external services.

## Local state and secrets

`state.sqlite3` is created beside the script and ignored by Git. Keep it across restarts to preserve polling offsets and webhook delivery receipts. Never commit `.env`, bot tokens, GitHub tokens, or webhook secrets. Remote API errors are deliberately sanitized so Telegram token-bearing URLs are not printed.
