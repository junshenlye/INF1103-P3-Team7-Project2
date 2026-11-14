import hashlib
import hmac
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import bot


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = patch.object(bot, 'ROOT', Path(self.temp.name))
        root.start()
        self.addCleanup(root.stop)
        self.bridge = bot.Bridge({
            'TELEGRAM_BOT_TOKEN': 'test-token', 'TELEGRAM_CHAT_ID': '-100123',
            'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_WEBHOOK_SECRET': 's' * 64,
        })
        self.messages = []
        self.bridge.send = self.messages.append
        self.payload = {
            'repository': {'full_name': 'owner/repo'}, 'action': 'closed',
            'pull_request': {'number': 7, 'merged': True, 'title': 'Feature',
                             'user': {'login': 'alice'}, 'html_url': 'https://github.com/owner/repo/pull/7'},
        }

    def test_merge_and_duplicate_delivery(self):
        self.bridge.handle_delivery('delivery-1', 'pull_request', self.payload)
        self.bridge.handle_delivery('delivery-1', 'pull_request', self.payload)
        self.assertEqual(len(self.messages), 1)
        self.assertIn('PR #7 merged', self.messages[0])

    def test_failed_send_can_be_retried(self):
        with patch.object(self.bridge, 'send', side_effect=bot.APIError('Unavailable')):
            with self.assertRaises(bot.APIError):
                self.bridge.handle_delivery('delivery-1', 'pull_request', self.payload)
        self.bridge.handle_delivery('delivery-1', 'pull_request', self.payload)
        self.assertEqual(len(self.messages), 1)

    def test_other_repository_is_ignored(self):
        self.payload['repository']['full_name'] = 'other/repo'
        self.bridge.handle_delivery('delivery-1', 'pull_request', self.payload)
        self.assertFalse(self.messages)

    def test_commands_restricted_to_group_and_bot(self):
        self.bridge.username = 'trackerbot'
        for chat, command in [('123', '/help'), ('-100123', '/help@otherbot')]:
            self.bridge.command({'message': {'chat': {'id': chat}, 'text': command}})
        self.assertFalse(self.messages)
        self.bridge.command({'message': {'chat': {'id': -100123}, 'text': '/help@trackerbot'}})
        self.assertIn('/prs', self.messages[0])

    def test_tasks_exclude_pull_requests(self):
        data = [{'number': 1, 'title': 'Task', 'html_url': 'https://github.com/owner/repo/issues/1'},
                {'number': 2, 'title': 'PR', 'pull_request': {}}]
        with patch.object(self.bridge, 'github', return_value=data):
            self.bridge.command({'message': {'chat': {'id': -100123}, 'text': '/tasks'}})
        self.assertIn('#1 Task', self.messages[0])
        self.assertNotIn('#2', self.messages[0])

    def test_coderabbit_comment(self):
        payload = {'repository': {'full_name': 'owner/repo'}, 'action': 'created',
                   'issue': {'number': 7, 'title': 'Feature', 'pull_request': {}},
                   'comment': {'user': {'login': 'coderabbitai[bot]'}, 'html_url': 'https://github.com/example'}}
        self.assertIn('CodeRabbit', bot.event_message('issue_comment', payload))
        payload['comment']['user']['login'] = 'someone'
        self.assertIsNone(bot.event_message('issue_comment', payload))

    def test_commands_only_does_not_open_a_web_server_or_require_webhook_secret(self):
        config = {'TELEGRAM_BOT_TOKEN': 'fake-token', 'TELEGRAM_CHAT_ID': '-100123',
                  'GITHUB_REPOSITORY': 'owner/repo'}
        with patch('sys.argv', ['bot.py', '--commands-only']), \
                patch.object(bot, 'load_config', return_value=config), \
                patch.object(bot, 'validate_connection'), \
                patch.object(bot, 'commands_only') as listener, \
                patch.object(bot, 'ThreadingHTTPServer') as server:
            bot.main()
        listener.assert_called_once()
        server.assert_not_called()

    def test_startup_checks_group_membership_without_sending(self):
        responses = [{'id': 12, 'username': 'tracker'}, {},
                     {'id': -100123, 'type': 'group'}, {'status': 'member'}]
        with patch.object(self.bridge, 'telegram', side_effect=responses) as telegram:
            bot.validate_connection(self.bridge)
        self.assertEqual([call.args[0] for call in telegram.call_args_list],
                         ['getMe', 'getWebhookInfo', 'getChat', 'getChatMember'])
        self.assertEqual(self.bridge.username, 'tracker')
        self.assertFalse(self.messages)

    def test_poll_records_successful_command(self):
        stop = threading.Event()

        def receive(_method, _payload):
            stop.set()
            return [{'update_id': 42, 'message': {'chat': {'id': -100123}, 'text': '/help'}}]

        with patch.object(self.bridge, 'telegram', side_effect=receive):
            self.bridge.poll(stop)
        self.assertEqual(self.bridge.setting('telegram_offset'), '43')
        self.assertEqual(self.bridge.setting('last_command'), '/help')
        self.assertTrue(self.bridge.setting('last_poll_at'))

    def test_http_signature_and_replay(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), bot.make_handler(self.bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        body = json.dumps(self.payload).encode()
        signature = 'sha256=' + hmac.new(self.bridge.secret.encode(), body, hashlib.sha256).hexdigest()
        for sig, expected in [('sha256=bad', 401), (signature, 200), (signature, 200)]:
            connection = http.client.HTTPConnection(*server.server_address)
            connection.request('POST', '/github', body=body, headers={
                'X-Hub-Signature-256': sig, 'X-GitHub-Delivery': 'test-delivery',
                'X-GitHub-Event': 'pull_request',
            })
            response = connection.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
            connection.close()
        self.assertEqual(len(self.messages), 1)


if __name__ == '__main__':
    unittest.main()
