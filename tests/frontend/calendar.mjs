// Focused scheduler interaction checks; no database or external services required.
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

const makeItem = (id, name, week, weight, moduleId = 'hsc') => ({
  assessment_id: id,
  name,
  week,
  end_week: week,
  weight_percent: weight,
  weight_scope: 'module',
  module_id: moduleId,
  module_title: moduleId === 'hsc' ? 'HSC1007' : 'INF1103',
});

const project = {
  id: 'calendar-test',
  name: 'Trimester 1',
  week_count: 14,
  status: 'Ready',
  modules: [
    { id: 'hsc', module_title: 'HSC1007' },
    { id: 'inf', module_title: 'INF1103' },
  ],
  issues: [],
};

const quiz = makeItem('quiz', 'CA1 MCQs Quiz', 7, 30);
const exam = makeItem('exam', 'CA3 MCQs', 13, 35);
const practical = makeItem('practical', 'OSPE Examination', 13, 35);
let items = [quiz, exam, practical];

const snapshot = () => ({
  ...project,
  schedule: {
    week_count: project.week_count,
    weeks: Array.from({ length: project.week_count }, (_, index) => ({
      week: index + 1,
      items: items.filter(item =>
        item.week != null
        && item.week <= index + 1
        && (item.end_week ?? item.week) >= index + 1,
      ),
    })),
    unscheduled: items.filter(item => item.week == null),
  },
});

await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));

let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE
      ? { executablePath: process.env.BROWSER_EXECUTABLE }
      : {}),
  });

  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.route('**/api/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    const limits = {
      module_count: 20,
      documents_per_module: 10,
      document_bytes: 10485760,
      request_bytes: 52428800,
      project_name_length: 150,
      module_title_length: 200,
      credit: 100,
      week_count: 52,
      media_types: ['application/pdf', 'image/png', 'image/jpeg'],
    };

    if (pathname === '/api/limits') return route.fulfill({ json: limits });
    if (pathname === '/api/projects') return route.fulfill({ json: [snapshot()] });
    if (pathname === '/api/projects/calendar-test') return route.fulfill({ json: snapshot() });
    return route.fulfill({
      status: 404,
      json: { issues: [{ message: 'Unknown calendar test route.' }] },
    });
  });

  const base = `http://127.0.0.1:${server.address().port}/?project=${project.id}`;
  const ready = () => page.getByRole('heading', { name: 'Your assessment schedule' }).waitFor();

  await page.goto(base);
  await ready();

  assert.equal(await page.locator('.week-tile').count(), 14);
  assert.equal(await page.locator('.calendar-event').count(), 3);
  assert.equal(await page.locator('.assessment-row:visible').count(), 0);
  assert.match(await page.locator('.week-tile[aria-label="Week 13"]').innerText(), /CA3 MCQs[\s\S]*OSPE Examination/);
  assert.equal(await page.getByRole('button', { name: 'Calendar', exact: true }).getAttribute('aria-pressed'), 'true');

  await page.getByRole('button', { name: 'Week 13, 2 assessments', exact: true }).click();
  assert.equal(await page.locator('.week-tile.is-selected .calendar-event').count(), 2);
  assert.equal(await page.locator('.assessment-row:visible').count(), 2);
  assert.equal(await page.locator('.week-tile.is-selected .calendar-week-button').evaluate(
    element => element === document.activeElement,
  ), true, 'Week selection restores focus to its calendar control');

  await page.getByRole('button', { name: 'Week 1, 0 assessments', exact: true }).click();
  assert.match(await page.locator('.agenda-empty').innerText(), /No assessments/);
  await page.getByRole('button', { name: 'Show all weeks', exact: true }).click();
  assert.equal(await page.locator('.assessment-row:visible').count(), 0);

  items = [
    ...items,
    { ...makeItem('range', 'Three-week project', 2, 25, 'inf'), end_week: 4, weight_scope: 'group' },
    makeItem('undated', 'Undated presentation', null, null, 'inf'),
  ];
  await page.reload();
  await ready();

  assert.equal(await page.locator('.calendar-event').count(), 6, 'A range appears in each covered week');
  assert.match(await page.locator('.module-filters').innerText(), /5 assessments/);

  const moduleColour = locator => locator.evaluate(
    element => getComputedStyle(element).getPropertyValue('--module-colour').trim(),
  );
  const infColour = await moduleColour(page.locator('.module-filters button[data-module="inf"]'));
  const hscColour = await moduleColour(page.locator('.module-filters button[data-module="hsc"]'));
  assert.notEqual(infColour, hscColour, 'Different modules receive different colours');

  await page.getByRole('button', { name: 'INF1103', exact: true }).click();
  assert.equal(await page.locator('.calendar-event').count(), 3);
  assert.match(await page.locator('.module-filters').innerText(), /2 assessments/);
  assert.equal(await moduleColour(page.locator('.calendar-event').first()), infColour);

  await page.getByRole('button', { name: 'Week 3, 1 assessments', exact: true }).click();
  assert.equal(await page.locator('.week-tile.is-selected .calendar-event').count(), 1);
  const href = await page.locator('.week-tile.is-selected [data-document-preview]').getAttribute('href');
  const sourceUrl = new URL(href, base);
  assert.equal(sourceUrl.pathname, '/documents');
  assert.equal(sourceUrl.searchParams.get('project'), project.id);
  assert.equal(sourceUrl.searchParams.get('module'), 'inf');
  assert.equal(sourceUrl.searchParams.get('week'), '3');
  assert.equal(sourceUrl.searchParams.get('assessment'), 'range');

  await page.goto(`${base}&layout=timeline&week=3&module=inf&assessment=range`);
  await ready();
  assert.equal(
    await page.evaluate(() => document.activeElement.matches('[data-document-preview]')),
    true,
    'Restoring a selected assessment focuses its source link',
  );
  assert.equal(
    await page.evaluate(() => new URL(document.activeElement.href).searchParams.get('assessment')),
    'range',
    'Focus returns to the selected assessment',
  );

  await page.getByRole('button', { name: 'Show all weeks', exact: true }).click();
  await page.getByRole('button', { name: 'Undated', exact: true }).click();
  assert.match(await page.locator('.agenda-heading').innerText(), /Undated assessments/);
  assert.match(await page.locator('.assessment-row:visible').innerText(), /Not dated[\s\S]*Undated presentation[\s\S]*Weight unknown/);

  await page.getByRole('button', { name: 'Show all weeks', exact: true }).click();
  await page.getByRole('button', { name: 'List', exact: true }).click();
  assert.equal(await page.locator('.term-map').isVisible(), false);
  assert.equal(await page.locator('.assessment-row:visible').count(), 2, 'List view filters by module and deduplicates ranges');
  assert.equal(await page.locator('.assessment-row:visible').filter({ hasText: 'Three-week project' }).count(), 1);
  assert.equal(await moduleColour(page.locator('.assessment-row:visible').first()), infColour);

  await page.reload();
  await ready();
  assert.equal(await page.getByRole('button', { name: 'List', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.getByRole('button', { name: 'INF1103', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('.assessment-row:visible').count(), 2, 'List and module selection survive reload');

  await page.getByRole('button', { name: 'All modules', exact: true }).click();
  assert.equal(await page.locator('.assessment-row:visible').count(), 5);
  assert.equal(await page.locator('.assessment-row:visible').filter({ hasText: 'Three-week project' }).count(), 1);
  assert.equal(await page.locator('.assessment-row:visible').filter({ hasText: 'Undated presentation' }).count(), 1);

  await page.getByRole('button', { name: 'Calendar', exact: true }).click();
  for (const width of [1440, 1024, 768, 700, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      `No horizontal page overflow at ${width}px`,
    );
    assert.ok(
      await page.locator('.week-navigator').evaluate(element => element.scrollWidth <= element.clientWidth),
      `Calendar grid fits at ${width}px`,
    );
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '/tmp/stackplan-calendar-mobile.png', fullPage: true });

  project.week_count = 6;
  items = Array.from({ length: 12 }, (_, index) =>
    makeItem(
      `dense-${index}`,
      `Assessment ${index + 1} with <img src=x onerror=alert(1)> in its title`,
      3,
      5,
    ),
  );
  await page.goto(base);
  await ready();
  assert.equal(await page.locator('.week-tile').count(), 6);
  assert.equal(await page.locator('.calendar-event').count(), 12);
  assert.equal(await page.locator('.calendar-event img').count(), 0, 'Assessment text is escaped');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

  items = [];
  await page.reload();
  await ready();
  assert.equal(await page.locator('.calendar-event').count(), 0);
  assert.match(await page.locator('.module-filters').innerText(), /0 assessments/);
  assert.deepEqual(pageErrors, []);

  console.log(
    'PASS calendar rendering, week selection, module filters, multi-week and undated assessments, source links, list view, reload persistence, escaping and responsive layouts',
  );
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
