"""Read a public source repository and send changed snapshots to Telegram."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_SOURCE = 'junshenlye/INF1103-P3-Team7-Project2'


class RemoteError(Exception):
    """A remote API failed without exposing response bodies or credentials."""


def request_json(url, headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, headers=headers or {}, data=data)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urlopen(req, timeout=45) as response:
            return json.load(response)
    except HTTPError as exc:
        # Telegram URLs contain the bot token: never print URLs/raw exceptions.
        raise RemoteError('API returned HTTP %s. Check access, repository name and rate limits.' % exc.code) from None
    except (URLError, OSError, ValueError):
        raise RemoteError('API unavailable or returned invalid JSON.') from None


class GitHub:
    """Read-only paginated access to one repository."""

    def __init__(self, source, token=''):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source):
            raise ValueError('SOURCE_REPOSITORY must be owner/repository.')
        self.source = source
        self.headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Team-PR-Watch'}
        if token:
            self.headers['Authorization'] = 'Bearer ' + token

    def pages(self, resource, params=None, field=None):
        query = dict(params or {}, per_page=100)
        for page in range(1, 101):
            data = request_json('https://api.github.com/repos/%s/%s?%s' % (
                self.source, resource, urlencode(query)), headers=self.headers)
            items = data[field] if field else data
            if not isinstance(items, list):
                raise RemoteError('Unexpected GitHub response.')
            yield from items
            if len(items) < 100:
                return
        raise RemoteError('Pagination exceeded 10,000 records; narrow the monitoring scope.')


def utc_text(value):
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def collect(api, since, now):
    """Collect the current PR/task/review/comment/CI snapshot."""
    records = {}

    def record(key, signature, message):
        records[key] = {'signature': signature, 'message': '[%s]\n%s' % (api.source, message),
                        'seen_at': utc_text(now)}

    pulls = {pr['number']: pr for pr in api.pages('pulls', {'state': 'open'})}
    for pr in api.pages('pulls', {'state': 'closed', 'sort': 'updated', 'direction': 'desc'}):
        if pr['updated_at'] < since:
            break
        pulls[pr['number']] = pr
    for number, pr in sorted(pulls.items()):
        status = 'merged' if pr.get('merged_at') else ('draft' if pr.get('draft') else pr['state'])
        owners = sorted(a['login'] for a in pr.get('assignees', []))
        reviewers = sorted(a['login'] for a in pr.get('requested_reviewers', []))
        signature = [status, pr['title'], pr['head']['sha'], owners, reviewers]
        record('pr:%s' % number, signature,
               'PR #%s %s: %s\nAuthor: %s\nAssignees: %s\nReview requested: %s\n%s' % (
                   number, status, pr['title'][:250], pr['user']['login'],
                   ', '.join(owners) or 'none', ', '.join(reviewers) or 'none', pr['html_url']))
        for review in api.pages('pulls/%s/reviews' % number):
            if review['state'] == 'PENDING':
                continue
            record('review:%s' % review['id'], review['state'],
                   'PR #%s review: %s — %s\n%s' % (
                       number, review['user']['login'], review['state'], review['html_url']))

    for issue in api.pages('issues', {'state': 'all', 'since': since}):
        if 'pull_request' in issue:
            continue
        owners = sorted(a['login'] for a in issue.get('assignees', []))
        record('issue:%s' % issue['number'], [issue['state'], issue['title'], owners],
               'Task #%s %s: %s\nAssignees: %s\n%s' % (
                   issue['number'], issue['state'], issue['title'][:250],
                   ', '.join(owners) or 'none', issue['html_url']))

    for comment in api.pages('issues/comments', {'since': since, 'sort': 'updated'}):
        if comment['user']['login'].lower() not in ('coderabbitai', 'coderabbitai[bot]'):
            continue
        if '/pull/' not in comment['html_url']:
            continue
        record('comment:%s' % comment['id'], comment['updated_at'],
               'CodeRabbit posted or updated a PR comment\n%s' % comment['html_url'])

    for run in api.pages('actions/runs', {
        'status': 'completed', 'created': '>=' + utc_text(now - timedelta(days=7)),
    }, field='workflow_runs'):
        record('run:%s' % run['id'], [run.get('run_attempt', 1), run.get('conclusion')],
               'CI: %s — %s\nBranch: %s | commit: %s\n%s' % (
                   run['name'], run.get('conclusion') or 'unknown', run.get('head_branch'),
                   run['head_sha'][:7], run['html_url']))
    return records


def save_state(path, state):
    """Atomically replace the snapshot file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, sort_keys=True))
    temporary.replace(path)


def apply_snapshot(state, records, source, now, send, save):
    """Send only changed records and persist each successful notification."""
    if not state:
        state = {'version': 1, 'source': source, 'records': records, 'last_scan': utc_text(now)}
        save(state)
        return 0
    if state.get('version') != 1 or state.get('source') != source:
        raise ValueError('State belongs to a different source/version. Reset it explicitly.')
    sent = 0
    for key, record in records.items():
        previous = state['records'].get(key)
        if previous is None or previous['signature'] != record['signature']:
            send(record['message'])
            sent += 1
        state['records'][key] = record
        save(state)
    cutoff = utc_text(now - timedelta(days=30))
    state['records'] = {k: v for k, v in state['records'].items() if v['seen_at'] >= cutoff}
    state['last_scan'] = utc_text(now)
    save(state)
    return sent


def telegram_sender(token, chat):
    """Build a plain-text sender after validating the secret formats."""
    if not token or not re.fullmatch(r'-[0-9]+', chat):
        raise ValueError('Set TELEGRAM_BOT_TOKEN and the negative group TELEGRAM_CHAT_ID as Actions secrets.')

    def send(message):
        result = request_json('https://api.telegram.org/bot%s/sendMessage' % token, payload={
            'chat_id': chat, 'text': message[:3000], 'link_preview_options': {'is_disabled': True},
        })
        if not result.get('ok'):
            raise RemoteError('Telegram rejected the notification.')
    return send


def validate_telegram(token, chat):
    """Verify the bot and intended group without sending a chat message."""
    for method, payload in [('getMe', {}), ('getChat', {'chat_id': chat})]:
        response = request_json('https://api.telegram.org/bot%s/%s' % (token, method), payload=payload)
        if not response.get('ok'):
            raise RemoteError('Telegram configuration could not be verified.')
        if method == 'getChat' and (
            str(response['result']['id']) != chat
            or response['result'].get('type') not in ('group', 'supergroup')
        ):
            raise ValueError('Configured Telegram chat must be the intended group.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Read source; send nothing and do not save state')
    parser.add_argument('--test', action='store_true', help='Explicitly send one connection-test message')
    args = parser.parse_args()
    try:
        source = os.environ.get('SOURCE_REPOSITORY', DEFAULT_SOURCE)
        path = Path(os.environ.get('STATE_PATH', '.state/watch.json'))
        state = json.loads(path.read_text()) if path.exists() else None
        if state and (state.get('version') != 1 or state.get('source') != source):
            raise ValueError('State belongs to another source/version; reset it explicitly.')
        now = datetime.now(timezone.utc)
        since = utc_text(datetime.fromisoformat(state['last_scan'].replace('Z', '+00:00')) - timedelta(minutes=10)) if state else utc_text(now - timedelta(days=1))
        api = GitHub(source, os.environ.get('SOURCE_GITHUB_TOKEN') or os.environ.get('GITHUB_TOKEN', ''))
        records = collect(api, since, now)
        if args.dry_run:
            print('Dry run: read %s records from %s. No messages sent; state unchanged.' % (len(records), source))
            return
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        chat = os.environ.get('TELEGRAM_CHAT_ID', '')
        send = telegram_sender(token, chat)
        validate_telegram(token, chat)
        if args.test:
            send('PR watcher connection test. Monitoring: ' + source)
        count = apply_snapshot(state, records, source, now, send, lambda value: save_state(path, value))
        print('Check complete: %s records; %s update notifications sent.' % (len(records), count))
        if state is None:
            print('Baseline saved. Future checks notify about changes.')
    except (RemoteError, ValueError, OSError, KeyError, TypeError):
        parser.exit(1, 'Check failed. Verify source repository/access, Actions secrets, API limits and state file.\n')


if __name__ == '__main__':
    main()
