// UI-only: serve static assets and intercept every API request in the browser.
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { chromium } from '../../frontend/node_modules/playwright/index.mjs';
const root = new URL('../../frontend/', import.meta.url);
const server = http.createServer(async (req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  const file = path === '/' ? 'templates/index.html' : path.startsWith('/static/') ? path.slice(1) : '';
  if (!file || file.includes('..')) return res.writeHead(404).end();
  try { res.writeHead(200, { 'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' }).end(await readFile(new URL(file, root))); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let stage = 'queued', terminal = '', failPoll = false, polls = 0;
  const documents = [
    { document_id: 'doc-1', module_id: 'inf1103', module_title: 'INF1103', filename: 'Assessment-brief.pdf', state: 'waiting' },
    { document_id: 'doc-2', module_id: 'inf1104', module_title: 'INF1104', filename: 'Assessment-brief.pdf', state: 'waiting' },
  ];
  const progress = () => ({ documents, total_documents: documents.length, extracted_documents: documents.filter(doc => doc.state === 'extracted').length });
  const project = { id: 'loading-test', name: 'Trimester 1', week_count: 14, status: 'Processing', job_id: 'job-test', modules: [], issues: [] };
  await page.route('**/api/**', async route => {
    assert.equal(route.request().method(), 'GET', 'Recovery must never resubmit');
    const path = new URL(route.request().url()).pathname;
    if (path.includes('/jobs/')) {
      polls++;
      if (failPoll) return route.fulfill({ status: 503, json: { issues: [{ message: 'Status temporarily unavailable.' }] } });
      return route.fulfill({ json: { id: 'job-test', status: terminal ? terminal : stage === 'queued' ? 'queued' : 'running', stage, progress: progress() } });
    }
    return route.fulfill({ json: path === '/api/limits' ? { module_count: 20, documents_per_module: 10, document_bytes: 10485760, request_bytes: 20971520, project_name_length: 150, module_title_length: 200, credit: 100, week_count: 52, media_types: ['application/pdf', 'image/png', 'image/jpeg'] } : path === '/api/projects' ? [project] : { ...project, status: terminal || project.status, schedule: terminal === 'Ready' ? { weeks: [], unscheduled: [] } : null } });
  });
  const base = `http://127.0.0.1:${server.address().port}/?project=loading-test`;
  const current = () => page.getByRole('heading', { name: /Building your schedule|Finishing up/ }).waitFor();
  await page.goto(base); await current();
  await page.waitForFunction(() => document.querySelectorAll('.checkpoint-list .is-done').length === 1);
  assert.equal(await page.locator('h1').count(), 1);
  assert.equal(await page.locator('#new-project').isVisible(), false, 'Navigation is absent during processing');
  assert.equal(await page.locator('#project-picker').isVisible(), false);
  assert.equal(await page.getByRole('navigation', { name: 'Loading demo scenarios' }).count(), 0);
  assert.equal(await page.locator('[role="progressbar"]').count(), 0, 'No fabricated percentage');
  assert.equal(await page.locator('[data-elapsed], .processing-badge, .document-progress').count(), 0, 'No detailed loading content');
  await page.evaluate(() => { window.loadingAnimation = document.querySelector('.loading-documents'); });
  assert.equal(await page.locator('.checkpoint-list li').count(), 3);
  assert.match(await page.locator('.checkpoint-list [aria-current]').innerText(), /Read assessments/);
  await page.locator('.processing-detail').filter({ hasText: 'Waiting to start' }).waitFor();
  stage = 'parsing'; documents[0].state = 'parsing';
  await page.locator('.processing-detail').filter({ hasText: 'Reading documents · 0/2 processed' }).waitFor();
  stage = 'extracting'; documents[0].state = 'extracted'; documents[1].state = 'extracting';
  await page.locator('.processing-detail').filter({ hasText: 'Extracting assessments · 1/2 processed' }).waitFor();
  const firstCell = page.locator('.paper-front');
  assert.equal(await firstCell.evaluate(el => getComputedStyle(el).animationName), 'paper-float');
  assert.equal(await page.evaluate(() => window.loadingAnimation === document.querySelector('.loading-documents')), true, 'Animation survives status updates');
  await page.reload(); await current();
  await page.waitForFunction(() => document.querySelectorAll('.checkpoint-list .is-done').length === 1);
  await page.waitForFunction(() => parseFloat(getComputedStyle(document.querySelector('.checkpoint-list .is-done path')).strokeDashoffset) === 0);
  await page.screenshot({ path: '/tmp/stackplan-document-progress-desktop.png', fullPage: true });
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Loading fits ${width}px`);
    assert.ok(await page.locator('.processing-panel').evaluate(el => el.scrollWidth <= el.clientWidth));
  }
  await page.screenshot({ path: '/tmp/stackplan-document-progress-mobile.png', fullPage: true });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const selector of ['.paper-front', '.checkpoint-list .is-active .checkpoint-dot']) assert.equal(await page.locator(selector).first().evaluate(el => getComputedStyle(el).animationName), 'none');
  documents[1].state = 'extracted'; stage = 'validating';
  await page.waitForFunction(() => document.querySelectorAll('.checkpoint-list .is-done').length === 2);
  assert.match(await page.locator('.checkpoint-list [aria-current]').innerText(), /Prepare schedule/);
  assert.equal(await page.locator('.processing-detail').innerText(), 'Checking sources');
  await page.screenshot({ path: '/tmp/stackplan-checkpoints-finishing.png', fullPage: true });
  assert.equal(await page.getByRole('heading', { name: 'Your assessment schedule', exact: true }).count(), 0, 'Extraction is not publication');
  stage = 'future-stage';
  await page.waitForTimeout(2100);
  await current();
  assert.match(await page.locator('.processing-detail').innerText(), /Processing documents/);
  terminal = 'Ready';
  await page.getByRole('heading', { name: 'Your schedule is ready.' }).waitFor();
  assert.equal(await page.locator('.completion-check').isVisible(), true);
  assert.equal(await page.locator('.loading-documents').isVisible(), false);
  assert.equal(await page.locator('.checkpoint-list .is-done').count(), 3);
  await page.getByRole('heading', { name: 'Your assessment schedule', exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-busy]'));
  assert.equal(await page.locator('#new-project').isDisabled(), false);
  // A fast job can skip every intermediate polling checkpoint.
  terminal = ''; stage = 'queued'; documents.forEach(doc => { doc.state = 'waiting'; });
  await page.goto(base); await current();
  terminal = 'Ready';
  await page.getByRole('heading', { name: 'Your schedule is ready.', exact: true }).waitFor();
  assert.equal(await page.locator('.completion-check').isVisible(), true, 'Fast completion still has a clear confirmation');
  assert.equal(await page.locator('.document-progress').count(), 0, 'Completion does not show stale waiting documents');
  await page.getByRole('heading', { name: 'Your assessment schedule', exact: true }).waitFor();
  terminal = ''; stage = 'parsing'; documents[0].state = 'parsing'; documents[1].state = 'waiting'; await page.goto(base); await current('Read documents');
  failPoll = true;
  await page.getByRole('heading', { name: 'Processing status unavailable' }).waitFor();
  assert.equal(await page.locator('[data-busy]').count(), 0, 'Error clears loading');
  assert.match(await page.locator('.document-progress').innerText(), /Last confirmed progress/);
  const stoppedAt = polls;
  await page.waitForTimeout(2200);
  assert.equal(polls, stoppedAt, 'No endless retry after error');
  failPoll = false;
  await page.getByRole('button', { name: 'Check submission status' }).click();
  await current('Read documents');
  assert.equal(await page.locator('h1').count(), 1, 'Recovery removes stale error heading');
  terminal = 'Failed'; documents[0].state = 'failed'; documents[1].state = 'not_processed';
  await page.getByRole('heading', { name: 'We could not finish processing' }).waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-busy]'));
  assert.equal(await page.locator('[data-document-state=failed]').count(), 1);
  assert.equal(await page.locator('[data-document-state=not_processed]').count(), 1);
  await page.reload();
  await page.locator('[data-document-state=failed]').waitFor();
  // Submission acceptance may already have a published result by the first GET.
  let acceptUpload;
  const acceptedUpload = new Promise(resolve => { acceptUpload = resolve; });
  await page.route('**/api/projects**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/process')) {
      await acceptedUpload;
      return route.fulfill({ status: 202, json: { job_id: 'instant-job', status: 'queued' } });
    }
    if (route.request().method() === 'POST') return route.fulfill({ status: 201, json: { ...project, id: 'instant', status: 'Created' } });
    return route.fulfill({ json: path === '/api/projects' ? [] : { ...project, id: 'instant', status: 'Ready', schedule: { weeks: [], unscheduled: [] } } });
  });
  await page.goto(base.split('?')[0]);
  await page.locator('#trimester-name').fill('Instant submission');
  await page.getByLabel('Module title').fill('INF1103');
  await page.locator('#module-images').setInputFiles({ name: 'sample.png', mimeType: 'image/png', buffer: Buffer.from('sample') });
  await page.getByRole('button', { name: 'Add module', exact: true }).click();
  await page.getByRole('button', { name: 'Review documents', exact: true }).click();
  await page.getByRole('button', { name: 'Build assessment schedule', exact: true }).click();
  await page.getByRole('heading', { name: 'Sending your documents…', exact: true }).waitFor();
  assert.equal(await page.locator('.input-workspace').isVisible(), false);
  acceptUpload();
  await page.getByRole('heading', { name: 'Your schedule is ready.', exact: true }).waitFor();
  assert.equal(await page.locator('.completion-check').isVisible(), true);
  assert.equal(await page.locator('.checkpoint-list .is-done').count(), 3);
  await page.getByRole('heading', { name: 'Your assessment schedule', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS focused loading screen, hidden navigation, document animation, backend status summaries, three checkpoints and reload, stable tick animations, fast submission, completion, responsive layout, reduced motion, recovery and failure; all API responses intercepted');
} finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
