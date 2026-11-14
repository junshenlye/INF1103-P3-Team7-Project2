// Browser regression for recovering a saved submission after a status-poll failure.
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
    const body = await readFile(path.join(frontendRoot, relative));
    response.writeHead(200, {
      'Content-Type': contentTypes[path.extname(relative)] || 'application/octet-stream',
      'Cache-Control': 'no-store',
    });
    response.end(body);
  } catch {
    response.writeHead(404).end();
  }
});

const assessment = {
  assessment_id: 'assessment-1',
  name: 'Programming assignment',
  week: 1,
  end_week: 1,
  weight_percent: 20,
  weight_scope: 'module',
  module_id: 'module-1',
  module_title: 'INF1103',
};

const readyProject = {
  id: 'recovery-test',
  name: 'Trimester 1',
  week_count: 2,
  status: 'Ready',
  job_id: 'job-test',
  modules: [{ id: 'module-1', module_title: 'INF1103' }],
  issues: [],
  schedule: {
    week_count: 2,
    weeks: [
      { week: 1, items: [assessment] },
      { week: 2, items: [] },
    ],
    unscheduled: [],
  },
};

const processingProject = {
  ...readyProject,
  status: 'Processing',
  schedule: null,
};

await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));

let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE
      ? { executablePath: process.env.BROWSER_EXECUTABLE }
      : {}),
  });

  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  let projectReads = 0;
  let jobReads = 0;
  let writes = 0;

  await page.route('**/api/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() !== 'GET') {
      writes++;
      return route.fulfill({ status: 405, json: { issues: [{ message: 'Writes are not expected.' }] } });
    }

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

    if (pathname === '/api/projects') {
      return route.fulfill({ json: [processingProject] });
    }

    if (pathname === '/api/projects/recovery-test/events') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': connected\n\n' });
    }

    if (pathname === '/api/projects/recovery-test') {
      projectReads++;
      return route.fulfill({ json: projectReads === 1 ? processingProject : readyProject });
    }

    if (pathname === '/api/jobs/job-test') {
      jobReads++;
      return route.fulfill({
        status: 503,
        json: { issues: [{ code: 'temporarily_unavailable', message: 'Status service temporarily unavailable.' }] },
      });
    }

    return route.fulfill({
      status: 404,
      json: { issues: [{ message: `Unexpected test route: ${pathname}` }] },
    });
  });

  await page.goto(`http://127.0.0.1:${server.address().port}/?project=recovery-test`);

  await page.getByRole('button', { name: 'Check submission status', exact: true }).waitFor();
  assert.equal(projectReads, 1, 'The saved Processing project was loaded once');
  assert.equal(jobReads, 1, 'The first status poll encountered the simulated outage');
  assert.equal(await page.getByRole('heading', { name: 'Processing status unavailable' }).count(), 1);
  assert.equal(await page.getByText('Last confirmed progress', { exact: true }).count(), 0);

  await page.getByRole('button', { name: 'Check submission status', exact: true }).click();

  await page.getByRole('heading', { name: 'Your assessment schedule', exact: true }).waitFor();
  assert.equal(await page.locator('.calendar-event').count(), 1, 'The recovered schedule is rendered');
  assert.match(await page.locator('.calendar-event').innerText(), /Programming assignment/);
  assert.equal(projectReads, 2, 'Recovery refreshes the saved project snapshot');
  assert.equal(jobReads, 1, 'A terminal saved project does not restart polling');
  assert.equal(writes, 0, 'Status recovery never resubmits the project or its documents');
  assert.deepEqual(pageErrors, []);

  console.log('PASS status-poll outage, explicit saved-project recovery, schedule restoration, and no duplicate submission');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
