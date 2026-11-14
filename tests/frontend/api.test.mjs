import test from 'node:test';
import assert from 'node:assert/strict';

import { request, submitBucket } from '../../frontend/static/api.js';

async function withFetch(mock, run) {
  const original = globalThis.fetch;
  globalThis.fetch = mock;
  try {
    await run();
  } finally {
    globalThis.fetch = original;
  }
}

test('structured server issues preserve their safe message, code, and status', async () => {
  await withFetch(
    async () => Response.json(
      { issues: [{ code: 'duplicate_module', message: 'Module titles must be distinct.' }] },
      { status: 409 },
    ),
    async () => {
      await assert.rejects(
        request('/api/projects/project/process'),
        error => error.status === 409
          && error.issues[0].code === 'duplicate_module'
          && error.message === 'Module titles must be distinct.'
          && error.uncertain === false,
      );
    },
  );
});

test('JSON requests encode their body and content type', async () => {
  const body = { name: 'Trimester 1', week_count: 14 };
  await withFetch(
    async (_path, options) => {
      assert.equal(options.method, 'POST');
      assert.equal(options.headers['Content-Type'], 'application/json');
      assert.equal(options.body, JSON.stringify(body));
      return Response.json({ id: 'project-1' });
    },
    async () => {
      const result = await request('/api/projects', { method: 'POST', body });
      assert.equal(result.id, 'project-1');
    },
  );
});

test('multipart submission preserves its browser boundary and idempotency key', async () => {
  const document = new Blob(['document bytes'], { type: 'application/pdf' });
  await withFetch(
    async (_path, options) => {
      assert.ok(options.body instanceof FormData);
      assert.equal(options.headers['Content-Type'], undefined);
      assert.equal(options.headers['Idempotency-Key'], 'browser-key');
      assert.deepEqual(
        JSON.parse(options.body.get('modules')),
        [{ module_title: 'INF1103', credit: 6, file_fields: ['file_0'] }],
      );
      assert.equal(options.body.get('file_0').type, 'application/pdf');
      return Response.json({ job_id: 'job-1', status: 'queued' }, { status: 202 });
    },
    async () => {
      const result = await submitBucket(
        'project-1',
        [{ module_title: 'INF1103', credit: 6, file_fields: ['file_0'] }],
        [['file_0', document]],
        'browser-key',
      );
      assert.equal(result.job_id, 'job-1');
    },
  );
});

test('a lost submission response is marked uncertain and is not retried', async () => {
  let calls = 0;
  await withFetch(
    async () => {
      calls += 1;
      throw new TypeError('network disconnected');
    },
    async () => {
      await assert.rejects(
        submitBucket('project-1', [], [], 'browser-key'),
        error => error.uncertain === true && error.message.includes('Check submission status'),
      );
      assert.equal(calls, 1);
    },
  );
});

test('aborted requests remain abort errors rather than uncertain submissions', async () => {
  const aborted = new DOMException('Request cancelled', 'AbortError');
  await withFetch(
    async () => { throw aborted; },
    async () => {
      await assert.rejects(request('/api/projects'), error => error === aborted);
    },
  );
});

test('unreadable JSON responses are marked uncertain', async () => {
  await withFetch(
    async () => ({
      ok: true,
      json: async () => { throw new SyntaxError('invalid JSON'); },
    }),
    async () => {
      await assert.rejects(
        request('/api/projects'),
        error => error.uncertain === true && error.message.includes('response could not be read'),
      );
    },
  );
});

test('server failures are marked uncertain while client validation errors are not', async () => {
  const responseFor = status => async () => Response.json(
    { issues: [{ code: 'processing_failed', message: 'Unable to process the request.' }] },
    { status },
  );

  await withFetch(responseFor(503), async () => {
    await assert.rejects(request('/api/projects'), error => error.status === 503 && error.uncertain);
  });
  await withFetch(responseFor(422), async () => {
    await assert.rejects(request('/api/projects'), error => error.status === 422 && !error.uncertain);
  });
});
