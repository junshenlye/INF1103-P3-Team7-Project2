import test from 'node:test';
import assert from 'node:assert/strict';
import { request, submitBucket } from '../../frontend/static/api.js';

test('structured issues retain safe messages and codes', async () => {
  const original = global.fetch;
  try {
    global.fetch = async () => Response.json({ issues: [{ code: 'duplicate_module', message: 'Module titles must be distinct.' }] }, { status: 409 });
    await assert.rejects(request('/api/projects/one/process'), error => error.status === 409 && error.issues[0].code === 'duplicate_module');
  } finally { global.fetch = original; }
});
test('bucket preserves browser multipart boundary and submission identity', async () => {
  const original = global.fetch;
  try {
    let sent;
    global.fetch = async (_, options) => { sent = options; return Response.json({ job_id: 'one', status: 'queued' }, { status: 202 }); };
    await submitBucket('project', [{ module_title: 'A', credit: 6, file_fields: ['file_0'] }], [['file_0', new Blob(['pdf'])]], 'browser-key');
    assert.ok(sent.body instanceof FormData);
    assert.equal(sent.headers['Content-Type'], undefined);
    assert.equal(sent.headers['Idempotency-Key'], 'browser-key');
    assert.equal(JSON.parse(sent.body.get('modules'))[0].file_fields[0], 'file_0');
  } finally { global.fetch = original; }
});
test('uncertain acceptance never automatically resends a POST', async () => {
  const original = global.fetch;
  try {
    let calls = 0;
    global.fetch = async () => { calls++; throw new TypeError('network disconnected'); };
    await assert.rejects(submitBucket('project', [], [], 'browser-key'), error => error.uncertain === true);
    assert.equal(calls, 1);
  } finally { global.fetch = original; }
});

test('replacement sends original bytes and retains uncertain acceptance', async () => {
 const original=global.fetch;
 try {
  const file=new File(['replacement bytes'],'source.pdf',{type:'application/pdf'});
  global.fetch=async (_,options)=>{assert.equal(options.body,file);assert.equal(options.headers['Content-Type'],'application/pdf');return Response.json({job_id:'job'},{status:202});};
  await request('/api/documents/doc/replacement',{method:'POST',body:file,headers:{'Content-Type':'application/pdf'}});
  global.fetch=async ()=>{throw new TypeError('Connection lost');};
  await assert.rejects(request('/api/documents/doc/replacement',{method:'POST',body:file}),error=>error.uncertain===true);
 } finally { global.fetch=original; }
});
