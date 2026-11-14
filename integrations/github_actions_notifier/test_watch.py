from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import watch

NOW = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
SOURCE = 'owner/project'


def record(signature):
    return {'signature': signature, 'message': 'Update', 'seen_at': watch.utc_text(NOW)}


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.saved = []

    def apply(self, state, records):
        return watch.apply_snapshot(state, records, SOURCE, NOW, self.sent.append,
                                    lambda value: self.saved.append(deepcopy(value)))

    def test_baseline_does_not_send_history(self):
        self.assertEqual(self.apply(None, {'pr:1': record('open')}), 0)
        self.assertFalse(self.sent)
        self.assertEqual(self.saved[-1]['source'], SOURCE)

    def test_only_changed_or_new_records_notify(self):
        self.apply(None, {'pr:1': record('open')})
        state = self.saved[-1]
        self.assertEqual(self.apply(state, {'pr:1': record('open')}), 0)
        self.assertEqual(self.apply(state, {'pr:1': record('merged'), 'review:1': record('APPROVED')}), 2)
        self.assertEqual(self.apply(state, {'pr:1': record('merged'), 'review:1': record('APPROVED')}), 0)

    def test_partial_failure_preserves_only_successful_notifications(self):
        self.apply(None, {})
        state = self.saved[-1]
        sender = unittest.mock.Mock(side_effect=[None, watch.RemoteError('Unavailable')])
        with self.assertRaises(watch.RemoteError):
            watch.apply_snapshot(state, {'pr:1': record('open'), 'pr:2': record('open')},
                                 SOURCE, NOW, sender, lambda value: self.saved.append(deepcopy(value)))
        self.assertIn('pr:1', self.saved[-1]['records'])
        self.assertNotIn('pr:2', self.saved[-1]['records'])

    def test_different_repository_state_is_rejected(self):
        with self.assertRaises(ValueError):
            self.apply({'version': 1, 'source': 'other/repo', 'records': {}}, {})
        self.assertFalse(self.sent)

    def test_collects_pr_reviews_coderabbit_tasks_and_ci(self):
        pr = {'number': 7, 'state': 'open', 'title': '$(untrusted input)', 'head': {'sha': 'abc'},
              'user': {'login': 'alice'}, 'html_url': 'https://github.com/owner/project/pull/7'}
        responses = {
            'pulls': [pr], 'pulls/7/reviews': [{'id': 8, 'state': 'APPROVED',
                'user': {'login': 'bob'}, 'html_url': 'https://github.com/review'}],
            'issues': [{'number': 2, 'state': 'open', 'title': 'Task', 'html_url': 'https://github.com/task'},
                       {'number': 7, 'pull_request': {}}],
            'issues/comments': [{'id': 9, 'updated_at': '2026-11-12T08:00:00Z',
                'user': {'login': 'coderabbitai[bot]'}, 'html_url': 'https://github.com/owner/project/pull/7#issuecomment-9'}],
            'actions/runs': [{'id': 10, 'name': 'Tests', 'conclusion': 'failure', 'head_branch': 'feature',
                             'head_sha': 'abcdefgh', 'html_url': 'https://github.com/run'}],
        }

        class FakeGitHub:
            source = SOURCE

            def pages(self, resource, params=None, field=None):
                if resource == 'pulls' and params.get('state') == 'closed':
                    return iter([])
                return iter(responses.get(resource, []))

        result = watch.collect(FakeGitHub(), '2026-11-11T00:00:00Z', NOW)
        self.assertEqual(set(result), {'pr:7', 'review:8', 'issue:2', 'comment:9', 'run:10'})
        self.assertIn('$(untrusted input)', result['pr:7']['message'])
        self.assertIn('failure', result['run:10']['message'])

    def test_telegram_uses_json_and_plain_text(self):
        with patch.object(watch, 'request_json', return_value={'ok': True}) as request:
            watch.telegram_sender('fake-token', '-123')('<b>plain text</b>')
        payload = request.call_args.kwargs['payload']
        self.assertEqual(payload['text'], '<b>plain text</b>')
        self.assertNotIn('parse_mode', payload)

    def test_atomic_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state' / 'watch.json'
            watch.save_state(path, {'records': {'pr:1': record('open')}})
            self.assertIn('pr:1', path.read_text())
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_configuration_verification_sends_no_messages(self):
        with patch.object(watch, 'request_json', side_effect=[
            {'ok': True, 'result': {'username': 'tracker'}},
            {'ok': True, 'result': {'id': -123, 'type': 'supergroup'}},
        ]) as request:
            watch.validate_telegram('fake-token', '-123')
        self.assertEqual([call.args[0].rsplit('/', 1)[-1] for call in request.call_args_list], ['getMe', 'getChat'])

    def test_configuration_rejects_another_group(self):
        with patch.object(watch, 'request_json', side_effect=[
            {'ok': True, 'result': {'username': 'tracker'}},
            {'ok': True, 'result': {'id': -456, 'type': 'group'}},
        ]):
            with self.assertRaises(ValueError):
                watch.validate_telegram('fake-token', '-123')


if __name__ == '__main__':
    unittest.main()
