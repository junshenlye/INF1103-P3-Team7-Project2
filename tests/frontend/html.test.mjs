import test from 'node:test';
import assert from 'node:assert/strict';
import { escape } from '../../frontend/static/html.js';

test('untrusted source wording cannot introduce HTML', () => {
  assert.equal(escape('<script>"x" & \'y\'</script>'), '&lt;script&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/script&gt;');
});
