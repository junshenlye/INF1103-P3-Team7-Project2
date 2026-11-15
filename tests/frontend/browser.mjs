// Browser regression for source evidence, citation overlays and the document viewer.
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
  const relative = pathname === '/documents'
    ? 'templates/documents.html'
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

const image = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jg2kAAAAASUVORK5CYII=',
  'base64',
);

const project = {
  id: 'project-1',
  name: 'Trimester 1',
  status: 'Ready',
  issues: [],
  modules: [{
    module_title: 'INF1103',
    assessments: [{ id: 'assessment-1', result_id: 'result-1' }],
  }],
};

const result = {
  assessments: [{
    id: 'assessment-1',
    facts: {
      name: 'Final exam',
      week: 12,
      end_week: 12,
      weight_percent: 40,
      weight_scope: 'module',
      parent_key: null,
      kind: 'individual',
    },
    evidence: {
      name: ['name-value', 'header-context'],
      week: ['week-value'],
      end_week: [],
      weight_percent: ['weight-value', 'header-context'],
      weight_scope: ['header-context'],
    },
  }],
};

const documents = [{
  id: 'document-1',
  filename: 'INF1103-assessment.png',
  media_type: 'image/png',
}];

const trace = {
  document_id: 'document-1',
  original_available: true,
  elements: [
    {
      id: 'name-value',
      text: 'Final exam <img src=x onerror=alert(1)>',
      regions: [{
        page: 1,
        bbox: [0.1, 0.1, 0.3, 0.2],
        coordinate_origin: 'TOPLEFT',
      }],
    },
    {
      id: 'week-value',
      text: 'Week 12',
      regions: [{
        page: 1,
        bbox: [0.4, 0.1, 0.6, 0.2],
        coordinate_origin: 'TOPLEFT',
      }],
    },
    {
      id: 'weight-value',
      text: '40%',
      regions: [{
        page: 1,
        bbox: [0.2, 0.4, 0.4, 0.5],
        coordinate_origin: 'TOPLEFT',
      }],
    },
    {
      id: 'header-context',
      text: 'Assessment | Due | Weight',
      regions: [{
        page: 1,
        bbox: [0.05, 0.02, 0.8, 0.08],
        coordinate_origin: 'TOPLEFT',
        role: 'column_header',
      }],
    },
  ],
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
  let traceReads = 0;
  let writes = 0;
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.route('**/api/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() !== 'GET') {
      writes++;
      return route.fulfill({
        status: 405,
        json: { issues: [{ message: 'The source viewer must remain read-only.' }] },
      });
    }

    if (pathname === '/api/projects/project-1') {
      return route.fulfill({ json: project });
    }
    if (pathname === '/api/results/result-1') {
      return route.fulfill({ json: result });
    }
    if (pathname === '/api/results/result-1/documents') {
      return route.fulfill({ json: documents });
    }
    if (pathname === '/api/documents/document-1/trace') {
      traceReads++;
      return route.fulfill({ json: trace });
    }
    if (pathname === '/api/documents/document-1/original') {
      return route.fulfill({ status: 200, contentType: 'image/png', body: image });
    }

    return route.fulfill({
      status: 404,
      json: { issues: [{ message: 'Unexpected source-viewer API request.' }] },
    });
  });

  const origin = 'http://127.0.0.1:' + server.address().port;
  await page.goto(origin + '/documents?project=project-1&assessment=assessment-1&field=weight_percent');

  await page.locator('#module-title').filter({ hasText: 'INF1103' }).waitFor();
  await page.locator('#assessment-title').filter({ hasText: 'Final exam' }).waitFor();
  await page.locator('.paper img').waitFor();
  await page.locator('.highlight').waitFor();

  assert.equal(traceReads, 1, 'The selected module source trace is fetched once and cached');
  assert.equal(await page.locator('#facts [data-field]').count(), 3);
  assert.equal(await page.locator('#facts [data-field="weight_percent"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#source-text [data-evidence-role="supporting"]').count(), 1);
  assert.equal(await page.locator('#source-text img').count(), 0, 'Untrusted source text is rendered as text, not HTML');
  assert.match(await page.locator('#source-text').innerText(), /40%/);
  assert.match(await page.locator('#source-text').innerText(), /Assessment \| Due \| Weight/);

  const highlights = page.locator('.highlight');
  assert.equal(await highlights.count(), 1, 'Only the selected value receives a source overlay');
  assert.equal(await highlights.first().evaluate(element => element.style.left), '20%');
  assert.equal(await highlights.first().evaluate(element => element.style.top), '40%');
  assert.equal(await page.locator('.context-highlight').count(), 0, 'Column headings remain supporting context');

  assert.equal(await page.locator('#source-links button').count(), 1, 'Evidence on the same page shares one page control');
  await page.locator('#source-links button').click();
  await page.locator('.highlight').waitFor();
  assert.equal(await page.locator('.highlight').count(), 1);
  assert.equal(await page.locator('#original').getAttribute('href'), '/api/documents/document-1/original');
  assert.equal(await page.locator('#original').getAttribute('aria-disabled'), null);

  await page.locator('#facts [data-field="name"]').click();
  await page.locator('#source-text').filter({ hasText: 'Final exam' }).waitFor();
  await page.locator('.highlight').waitFor();
  assert.equal(traceReads, 1, 'Changing facts reuses the cached source trace');
  assert.equal(await page.locator('.highlight').count(), 1);
  assert.equal(await page.locator('#source-text img').count(), 0);

  const back = new URL(await page.locator('#return-schedule').getAttribute('href'), origin);
  assert.equal(back.pathname, '/');
  assert.equal(back.searchParams.get('project'), 'project-1');
  assert.equal(back.searchParams.get('assessment'), 'assessment-1');
  assert.equal(back.searchParams.get('view'), 'schedule');

  for (const width of [1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      'Source viewer has no horizontal page overflow at ' + width + 'px',
    );
  }

  assert.equal(writes, 0, 'Inspecting source evidence never changes server data');
  assert.deepEqual(pageErrors, []);
  console.log('PASS source evidence, selected-value overlays, cached traces, safe text rendering, page controls, return navigation and responsive layout');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
