"""Standalone Telegram/GitHub bridge. Uses only Python's standard library."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


class APIError(Exception):
    pass


def load_config():
    # Dedicated file: never loads the application's provider credentials.
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and not key.strip().startswith('#'):
                values[key.strip()] = value.strip()
    values.update(os.environ)
    return values


def request_json(url, payload=None, headers=None, timeout=45):
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=body, headers=headers or {})
    if body is not None:
        request.add_header('Content-Type', 'application/json')
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        # URLs for Telegram contain the token. Never log them or raw exceptions.
        raise APIError('Remote API returned HTTP %s' % exc.code) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise APIError('Remote API unavailable or returned invalid JSON') from None


class Bridge:
    def __init__(self, config):
        self.token = config.get('TELEGRAM_BOT_TOKEN', '')
        self.chat = config.get('TELEGRAM_CHAT_ID', '')
        self.repo = config.get('GITHUB_REPOSITORY', '')
        self.secret = config.get('GITHUB_WEBHOOK_SECRET', '')
        self.github_token = config.get('GITHUB_TOKEN', '')
        self.database = ROOT / 'state.sqlite3'
        self.lock = threading.Lock()
        self.username = ''
        if not self.token:
            raise ValueError('Set TELEGRAM_BOT_TOKEN in the bot .env file.')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repo):
            raise ValueError('GITHUB_REPOSITORY must be owner/repository.')
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, created REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')

    def telegram(self, method, payload):
        result = request_json('https://api.telegram.org/bot%s/%s' % (self.token, method), payload)
        if not result.get('ok'):
            raise APIError('Telegram rejected the request')
        return result['result']

    def github(self, resource):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Stackplan-Telegram-Bot'}
        if self.github_token:
            headers['Authorization'] = 'Bearer ' + self.github_token
        return request_json('https://api.github.com/repos/%s/%s' % (self.repo, resource), headers=headers)

    def send(self, message):
        # Plain text prevents repository content from injecting formatting/mentions.
        for start in range(0, len(message), 3000):
            self.telegram('sendMessage', {
                'chat_id': self.chat, 'text': message[start:start + 3000],
                'link_preview_options': {'is_disabled': True},
            })

    def setting(self, key, value=None):
        with sqlite3.connect(self.database) as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, str(value)))
            row = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
            return row[0] if row else None

    def handle_delivery(self, delivery, event, payload):
        if payload.get('repository', {}).get('full_name', '').lower() != self.repo.lower():
            return
        message = event_message(event, payload)
        if not message:
            return
        # Serialize concurrent GitHub retries and acknowledge only successful sends.
        with self.lock, sqlite3.connect(self.database) as db:
            if db.execute('SELECT 1 FROM deliveries WHERE id = ?', (delivery,)).fetchone():
                return
            self.send(message)
            db.execute('INSERT INTO deliveries VALUES (?, ?)', (delivery, time.time()))
            db.execute('DELETE FROM deliveries WHERE created < ?', (time.time() - 30 * 86400,))

    def command(self, update):
        message = update.get('message', {})
        if str(message.get('chat', {}).get('id', '')) != self.chat:
            return
        text = message.get('text', '')
        if not text.startswith('/'):
            return
        command = text.split()[0]
        name, _, target = command.partition('@')
        if target and target.lower() != self.username.lower():
            return
        if name in ('/start', '/help'):
            self.send('GitHub tracker: %s\n/prs — open pull requests\n/tasks — open GitHub Issues\n/help — commands' % self.repo)
            return True
        elif name in ('/prs', '/tasks'):
            resource = 'pulls' if name == '/prs' else 'issues'
            items = self.github(resource + '?' + urlencode({'state': 'open', 'per_page': 100}))
            items = [i for i in items if resource == 'pulls' or 'pull_request' not in i]
            lines = ['Open %s — %s' % ('PRs' if resource == 'pulls' else 'tasks', self.repo)]
            for item in items[:20]:
                owners = ', '.join(a['login'] for a in item.get('assignees', [])) or 'unassigned'
                lines.append('#%s %s\nOwner: %s\n%s' % (item['number'], item['title'][:200], owners, item['html_url']))
            if not items:
                lines.append('None currently open.')
            if len(items) > 20:
                lines.append('Showing the first 20. See https://github.com/%s/%s for all items.' % (self.repo, resource))
            self.send('\n\n'.join(lines))
            return True

    def poll(self, stop):
        offset = int(self.setting('telegram_offset') or '0')
        while not stop.is_set():
            try:
                updates = self.telegram('getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message']})
                self.setting('last_poll_at', time.time())
                for update in updates:
                    try:
                        if self.command(update):
                            name = update['message']['text'].split()[0].split('@')[0]
                            self.setting('last_command', name)
                            self.setting('last_command_at', time.time())
                            print('Replied to %s in the configured group.' % name, flush=True)
                    except APIError:
                        print('Command could not be completed. Check API access/rate limits.', flush=True)
                    offset = update['update_id'] + 1
                    self.setting('telegram_offset', offset)
            except APIError as exc:
                print(str(exc), flush=True)
                stop.wait(10)


def event_message(event, payload):
    action = payload.get('action', '')
    repo = payload.get('repository', {}).get('full_name', '')
    if event == 'pull_request' and action in ('opened', 'reopened', 'closed', 'ready_for_review', 'review_requested'):
        pr = payload['pull_request']
        status = 'merged' if action == 'closed' and pr.get('merged') else action.replace('_', ' ')
        return '[%s] PR #%s %s\n%s\nAuthor: %s\n%s' % (
            repo, pr['number'], status, pr['title'][:300], pr['user']['login'], pr['html_url'])
    if event == 'pull_request_review' and action == 'submitted':
        review, pr = payload['review'], payload['pull_request']
        return '[%s] Review on PR #%s\n%s: %s\n%s' % (
            repo, pr['number'], review['user']['login'], review['state'], review['html_url'])
    if event == 'issue_comment' and action == 'created':
        comment, issue = payload['comment'], payload['issue']
        if 'pull_request' in issue and comment['user']['login'].lower() in ('coderabbitai', 'coderabbitai[bot]'):
            return '[%s] CodeRabbit commented on PR #%s\n%s\n%s' % (
                repo, issue['number'], issue['title'][:300], comment['html_url'])
    if event == 'workflow_run' and action == 'completed':
        run = payload['workflow_run']
        return '[%s] CI: %s — %s\nBranch: %s | commit: %s\n%s' % (
            repo, run['name'], run.get('conclusion') or 'unknown',
            run.get('head_branch') or 'unknown', run.get('head_sha', '')[:7], run['html_url'])
    if event == 'issues' and action in ('opened', 'assigned', 'unassigned', 'closed', 'reopened'):
        issue = payload['issue']
        owners = ', '.join(a['login'] for a in issue.get('assignees', [])) or 'unassigned'
        return '[%s] Task #%s %s\n%s\nOwner: %s\n%s' % (
            repo, issue['number'], action, issue['title'][:300], owners, issue['html_url'])
    return None


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200 if self.path == '/health' else 404)
            self.end_headers()
            if self.path == '/health':
                self.wfile.write(b'ok')

        def do_POST(self):
            if self.path != '/github':
                self.send_error(404)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400)
                return
            if size <= 0 or size > 2 * 1024 * 1024:
                self.send_error(413)
                return
            self.connection.settimeout(15)
            body = self.rfile.read(size)
            expected = 'sha256=' + hmac.new(bridge.secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, self.headers.get('X-Hub-Signature-256', '')):
                self.send_error(401)
                return
            delivery = self.headers.get('X-GitHub-Delivery', '')
            if not delivery or len(delivery) > 200:
                self.send_error(400)
                return
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError()
                bridge.handle_delivery(delivery, self.headers.get('X-GitHub-Event', ''), payload)
            except (ValueError, KeyError, TypeError, AttributeError):
                self.send_error(400)
                return
            except (APIError, sqlite3.Error):
                self.send_error(503)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
    return Handler


def discover(bridge):
    me = bridge.telegram('getMe', {})
    print('Bot: @' + me['username'], flush=True)
    print('Add this bot to your group and send /setup@%s there.' % me['username'])
    print('Waiting up to 30 seconds for group commands; no messages will be sent.')
    updates = bridge.telegram('getUpdates', {'timeout': 25, 'allowed_updates': ['message']})
    found = set()
    for update in updates:
        message = update.get('message', {})
        chat = message.get('chat', {})
        if chat.get('type') in ('group', 'supergroup') and message.get('text', '').startswith('/setup'):
            found.add((chat['id'], chat.get('title', 'Group')))
    for chat_id, title in sorted(found):
        print('%s: TELEGRAM_CHAT_ID=%s' % (title, chat_id))
    if not found:
        print('No group setup command found. Send it in the group, then run --discover again.')


def validate_connection(bridge):
    me = bridge.telegram('getMe', {})
    bridge.username = me['username']
    if bridge.telegram('getWebhookInfo', {}).get('url'):
        raise ValueError('This bot already uses a Telegram webhook. Use a dedicated bot or remove that webhook first.')
    chat = bridge.telegram('getChat', {'chat_id': bridge.chat})
    if str(chat['id']) != bridge.chat or chat.get('type') not in ('group', 'supergroup'):
        raise ValueError('The configured chat must be the intended Telegram group.')
    membership = bridge.telegram('getChatMember', {'chat_id': bridge.chat, 'user_id': me['id']})
    if membership.get('status') in ('left', 'kicked') or (
        membership.get('status') == 'restricted' and not membership.get('can_send_messages')
    ):
        raise ValueError('The bot must be a group member with permission to send messages.')


def commands_only(bridge):
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_args: stop.set())
    print('Command listener ready: @%s, repository %s. No HTTP listener.' % (
        bridge.username, bridge.repo), flush=True)
    bridge.poll(stop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover', action='store_true', help='Print bot identity and group IDs; send nothing')
    parser.add_argument('--commands-only', action='store_true', help='Listen for group commands without running a webhook server')
    args = parser.parse_args()
    config = load_config()
    try:
        bridge = Bridge(config)
        if args.discover:
            discover(bridge)
            return
        if not re.fullmatch(r'-[0-9]+', bridge.chat):
            raise ValueError('Set the negative group TELEGRAM_CHAT_ID.')
        if not args.commands_only and len(bridge.secret) < 32:
            raise ValueError('Set a webhook secret of at least 32 characters.')
        validate_connection(bridge)
        if args.commands_only:
            commands_only(bridge)
            return
        server = ThreadingHTTPServer(('0.0.0.0', int(config.get('PORT', '8088'))), make_handler(bridge))
        stop = threading.Event()
        thread = threading.Thread(target=bridge.poll, args=(stop,), daemon=True)
        thread.start()
        print('Tracker running for %s. GitHub webhook path: /github' % bridge.repo, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            server.server_close()
    except (ValueError, APIError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
