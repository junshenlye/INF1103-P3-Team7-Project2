import assert from 'node:assert/strict';
import test from 'node:test';

import { ProcessingEvents } from '../../frontend/static/processing-events.js';

test('progress events wake the poller for completed document updates', async () => {
  const original = globalThis.EventSource;
  let stream;
  globalThis.EventSource = class extends EventTarget {
    constructor(url) {
      super();
      this.url = url;
      this.closed = false;
      stream = this;
    }
    close() { this.closed = true; }
  };

  try {
    const updates = new ProcessingEvents('project / 1');
    assert.equal(stream.url, '/api/projects/project%20%2F%201/events');

    let finished = false;
    const waiting = updates.wait(1000).then(() => { finished = true; });
    stream.dispatchEvent(new MessageEvent('progress', {
      data: JSON.stringify({ kind: 'document.completed' }),
    }));
    await waiting;

    assert.equal(finished, true);
    updates.close();
    assert.equal(stream.closed, true);
  } finally {
    globalThis.EventSource = original;
  }
});

test('unrelated and malformed events leave the timed fallback active', async () => {
  const original = globalThis.EventSource;
  let stream;
  globalThis.EventSource = class extends EventTarget {
    constructor() { super(); stream = this; }
    close() {}
  };

  try {
    const updates = new ProcessingEvents('project-id');
    const started = Date.now();
    const waiting = updates.wait(20);
    stream.dispatchEvent(new MessageEvent('progress', {
      data: JSON.stringify({ kind: 'document.started' }),
    }));
    stream.dispatchEvent(new MessageEvent('progress', { data: '{invalid' }));
    await waiting;
    assert.ok(Date.now() - started >= 10);
    updates.close();
  } finally {
    globalThis.EventSource = original;
  }
});

test('closing the stream releases a pending wait', async () => {
  const original = globalThis.EventSource;
  globalThis.EventSource = class extends EventTarget {
    close() {}
  };

  try {
    const updates = new ProcessingEvents('project-id');
    let finished = false;
    const waiting = updates.wait(1000).then(() => { finished = true; });
    updates.close();
    await waiting;
    assert.equal(finished, true);
  } finally {
    globalThis.EventSource = original;
  }
});
