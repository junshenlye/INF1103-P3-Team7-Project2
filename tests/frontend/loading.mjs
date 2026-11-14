// Browser regression for the destination's processing and loading experience.
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import { chromium } from '../../frontend/node_modules/playwright/index.mjs';

const frontendRoot = fileURLToPath(new URL('../../frontend/', import.meta.url));
const contentTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
};

const server = http.createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname;
  const relative = pathname === '/'
    ? 'templates/index.html'
    : pathname.startsWith('/static/')
      ? pathname.slice(1)
      : '';

  if (!relative || relative.split('/').includes('..')) {
    response.writeHead(404).end();
    return;
  }

  try {
    const file = path.join(frontendRoot, relative);
    const body = await readFile(file);
    response.writeHead(200, {
      'Content-Type': contentTypes[path.extname(file)] || 'application/octet-stream',
      'Cache-Control': 'no-store',
    });
    response.end(body);
  } catch {
    response.writeHead(404).end();
  }
});

let projectStatus = 'Processing';
let jobStatus = 'running';
let stage = 'queued';
const documents = [
  {
    document_id: 'document-1',
    module_id: 'module-1',
    module_title: 'INF1103',
    filename: 'Assessment-brief.pdf',
    state: 'waiting',
  },
  {
    document_id: 'document-2',
    module_id: 'module-2',
    module_title: 'INF1104',
    filename: 'Assessment-guide.pdf',
    state: 'waiting',
  },
];

const progress = () => ({
  documents,
  total_documents: documents.length,
  extracted_documents: documents.filter(document => document.state === 'extracted').length,
});

const project = () => ({
  id: 'loading-test',
  name: 'Trimester 1',
  week_count: 14,
  status: projectStatus,
  job_id: 'job-test',
  modules: [],
  schedule: projectStatus === 'Ready' ? { weeks: [], unscheduled: [] } : null,
  issues: [],
});

const job = () => ({ id: 'job-test', status: jobStatus, stage, progress: progress() });

await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));

let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE
      ? { executablePath: process.env.BROWSER_EXECUTABLE }
      : {}),
  });

  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.route('**/api/**', async route => {
    assert.equal(route.request().method(), 'GET', 'Loading recovery must not submit data again');
    const pathname = new URL(route.request().url()).pathname;

    if (pathname === '/api/limits') {
      return route.fulfill({
        json: {
          request_bytes: 52428800,
          document_bytes: 10485760,
          module_count: 20,
          documents_per_module: 10,
          project_name_length: 150,
          module_title_length: 200,
          credit: 100,
          week_count: 52,
          media_types: ['application/pdf', 'image/png', 'image/jpeg'],
        },
      });
    }
    if (pathname === '/api/projects') return route.fulfill({ json: [project()] });
    if (pathname === '/api/projects/loading-test') return route.fulfill({ json: project() });
    if (pathname === '/api/jobs/job-test') return route.fulfill({ json: job() });
    return route.fulfill({ status: 404, json: { issues: [{ message: 'Unknown test route.' }] } });
  });

  await page.goto(`http://127.0.0.1:${server.address().port}/?project=loading-test`);
  await page.getByRole('heading', { name: 'Making room for the work ahead.' }).waitFor();

  const stages = page.locator('.processing-stages li');
  assert.equal(await stages.count(), 4, 'The four processing stages are visible');
  await page.waitForFunction(() =>
    document.querySelector('.processing-stages li[aria-current="step"]')?.textContent.includes('Queued'),
  );
  await page.locator('.document-progress-item[data-document-id="document-1"]').waitFor();
  assert.match(await page.locator('.document-progress-heading').innerText(), /0 of 2 documents extracted/);
  assert.equal(await page.locator('.processing-live[role="status"]').count(), 1);

  stage = 'parsing';
  documents[0].state = 'parsing';
  await page.waitForFunction(() =>
    document.querySelector('.processing-stages li[aria-current="step"]')?.textContent.includes('Read documents'),
  );
  await page.locator('.document-progress-item[data-document-id="document-1"][data-document-state="parsing"]').waitFor();
  await page.locator('.processing-live').filter({ hasText: 'Reading Assessment-brief.pdf' }).waitFor();

  stage = 'extracting';
  documents[0].state = 'extracted';
  documents[1].state = 'extracting';
  await page.waitForFunction(() =>
    document.querySelector('.processing-stages li[aria-current="step"]')?.textContent.includes('Find assessments'),
  );
  await page.locator('.document-progress-item[data-document-id="document-2"][data-document-state="extracting"]').waitFor();
  await page.getByText('1 of 2 documents extracted', { exact: true }).waitFor();

  stage = 'validating';
  documents[1].state = 'extracted';
  await page.waitForFunction(() =>
    document.querySelector('.processing-stages li[aria-current="step"]')?.textContent.includes('Check sources'),
  );
  await page.getByText('2 of 2 documents extracted', { exact: true }).waitFor();
  await page.locator('.processing-live').filter({ hasText: 'Checking facts and source evidence.' }).waitFor();

  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const selector of ['.loader-stack i', '.loading-track span']) {
    assert.equal(
      await page.locator(selector).first().evaluate(element => getComputedStyle(element).animationName),
      'none',
      `Reduced-motion mode disables ${selector} animation`,
    );
  }

  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const dimensions = await page.evaluate(() => ({
      viewport: innerWidth,
      document: document.documentElement.scrollWidth,
      panel: document.querySelector('.processing-panel')?.scrollWidth,
      panelClient: document.querySelector('.processing-panel')?.clientWidth,
    }));
    assert.ok(dimensions.document <= dimensions.viewport, `Processing layout fits ${width}px`);
    assert.ok(dimensions.panel <= dimensions.panelClient, `Processing panel fits ${width}px`);
  }

  projectStatus = 'Ready';
  jobStatus = 'succeeded';
  await page.getByRole('heading', { name: 'Your assessment schedule', exact: true }).waitFor({ timeout: 10000 });
  await page.waitForFunction(() => !document.querySelector('[data-loading]'));
  assert.deepEqual(pageErrors, []);

  console.log(
    'PASS processing checkpoints, document progress updates, completion, responsive layout and reduced-motion accessibility',
  );
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
