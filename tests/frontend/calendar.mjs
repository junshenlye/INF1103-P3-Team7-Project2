// Focused scheduler interaction checks; no database or external services required.
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { chromium } from '../../frontend/node_modules/playwright/index.mjs';

const root = new URL('../../frontend/', import.meta.url);
const server = http.createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname;
  const file = pathname === '/' ? 'templates/index.html' : pathname.startsWith('/static/') ? pathname.slice(1) : '';
  if (!file || file.includes('..')) { response.writeHead(404).end(); return; }
  try {
    const body = await readFile(new URL(file, root));
    const type = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
    response.writeHead(200, { 'Content-Type': type }); response.end(body);
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const item = (id, name, week, weight, module = 'hsc') => ({ assessment_id: id, name, week, end_week: week, weight_percent: weight, weight_scope: 'module', module_id: module, module_title: module === 'hsc' ? 'HSC1007' : 'INF1103' });
  const quiz = item('quiz', 'CA1 MCQs Quiz (Week 1–7)', 8, 30);
  const exam = item('exam', 'CA3 MCQs (Week 8–13)', 13, 35);
  const spot = item('spot', 'OSPE/Spot Examination (Week 1–13)', 13, 35);
  let items = [quiz, exam, spot];
  const project = { id: 'calendar-test', name: 'Trialtest01', week_count: 14, status: 'Ready', modules: [{ id: 'hsc', module_title: 'HSC1007' }, { id: 'inf', module_title: 'INF1103' }], issues: [] };
  const schedule = () => ({ week_count: project.week_count, weeks: Array.from({ length: project.week_count }, (_, index) => ({ week: index + 1, items: items.filter(item => item.week != null && item.week <= index + 1 && (item.end_week ?? item.week) >= index + 1) })), unscheduled: items.filter(item => item.week == null) });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const json = path === '/api/limits' ? {module_count:20,documents_per_module:10,document_bytes:10485760,request_bytes:52428800,project_name_length:150,module_title_length:200,credit:100,week_count:52,media_types:['application/pdf','image/png','image/jpeg']} : path === '/api/projects' ? [project] : { ...project, schedule: schedule() };
    return route.fulfill({ json });
  });
  const base = `http://127.0.0.1:${server.address().port}/?project=${project.id}`;
  const ready = () => page.getByRole('heading', { name: 'Your assessment schedule' }).waitFor();
  await page.goto(base); await ready();
  assert.equal(await page.locator('.week-tile').count(), 14);
  assert.equal(await page.locator('.calendar-event').count(), 3);
  assert.equal(await page.locator('.week-navigator .calendar-event').count(),3, 'Assessment details live inside the calendar');
  assert.equal(await page.locator('.assessment-row').count(), 0, 'Calendar shows cards, not a duplicate table');
  assert.match(await page.getByRole('region', {name:'Week 13 assessments',exact:true}).innerText(), /CA3 MCQs[\s\S]*OSPE/);
  assert.equal(await page.getByRole('button', { name: 'Calendar', exact: true }).getAttribute('aria-pressed'), 'true');
  await page.screenshot({ path: '/tmp/stackplan-calendar-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Week 13, 2 assessments', exact: true }).click();
  assert.equal(await page.locator('.week-tile.is-selected .calendar-event').count(), 2);
  assert.equal(await page.locator('.calendar-event:visible').count(), 3, 'Highlighting a week keeps the rest of the calendar readable');
  await page.getByRole('button', { name: 'Week 1, 0 assessments', exact: true }).click();
  assert.match(await page.locator('.week-tile.is-selected').innerText(), /No assessments/);
  await page.getByRole('button', { name: 'Show all weeks', exact: true }).click();
  assert.equal(await page.locator('.calendar-event').count(),3);

  items.push({ ...item('range', 'Three-week project', 2, 25, 'inf'), end_week: 4, weight_scope: 'group' }, item('undated', 'Undated presentation', null, null, 'inf'));
  await page.reload(); await ready();
  assert.equal(await page.locator('.calendar-event').count(), 7, 'Ranges appear in every covered week and undated work remains visible');
  assert.match(await page.locator('.module-filters').innerText(), /5 assessments/);
  const colour = locator => locator.evaluate(el => getComputedStyle(el).getPropertyValue('--module-colour').trim());
  const infColour = await colour(page.locator('[data-module="inf"]'));
  assert.notEqual(infColour, await colour(page.locator('[data-module="hsc"]')), 'Different module IDs have different colours');
  assert.equal(await colour(page.locator('.calendar-event[href*="assessment=range"]').first()), infColour, 'Legend matches events');
  await page.getByRole('button', { name: 'INF1103', exact: true }).click();
  assert.equal(await colour(page.locator('.calendar-event').first()), infColour, 'Filtering preserves colours');
  assert.equal(await page.locator('.calendar-event').count(), 4);
  assert.match(await page.locator('.module-filters').innerText(), /2 assessments/);
  await page.getByRole('button', { name: 'Week 3, 1 assessments', exact: true }).click();
  assert.equal(await page.locator('.week-tile.is-selected .calendar-event').count(), 1);
  assert.match(await page.locator('.week-tile.is-selected').innerText(), /25% of group[\s\S]*Weeks 2–4/);
  const href = await page.locator('.week-tile.is-selected [data-document-preview]').getAttribute('href');
  const source = new URL(href, base);
  assert.equal(source.pathname, '/documents');
  assert.equal(source.searchParams.get('module'), 'inf');
  assert.equal(source.searchParams.get('week'), '3');
  assert.equal(source.searchParams.get('assessment'), 'range');
  // Source return restores selection and a visible assessment link's focus.
  await page.goto(`${base}&layout=timeline&week=3&module=inf&assessment=range`); await ready();
  assert.equal(await page.evaluate(() => document.activeElement.matches('[data-document-preview]')), true);
  assert.equal(await page.evaluate(() => Boolean(document.activeElement.closest('.week-tile.is-selected'))), true, 'Source return focuses the assessment in the selected week');
  await page.getByRole('button', { name: 'Undated', exact: true }).click();
  assert.match(await page.locator('.undated-assessments').innerText(), /Undated presentation[\s\S]*Weight unknown/);
  await page.getByRole('button', { name: 'Show all weeks', exact: true }).click();
  await page.getByRole('button', { name: 'List', exact: true }).click();
  assert.equal(await page.locator('.term-map').isVisible(), false);
  assert.equal(await page.locator('.assessment-row:visible').count(), 2, 'List deduplicates ranges');
  assert.equal(await colour(page.locator('.assessment-row:visible').first()), infColour, 'List uses the calendar colour');
  project.modules.reverse();
  await page.reload(); await ready();
  assert.equal(await page.getByRole('button', { name: 'List', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await colour(page.locator('.assessment-row:visible').first()), infColour, 'Reload and reordered modules retain colours');
  assert.equal(await page.getByRole('button', { name: 'INF1103', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.match(await page.locator('.list-filter-summary').innerText(), /Showing 2 of 5[\s\S]*INF1103[\s\S]*All weeks/);
  await page.getByLabel('Teaching week', {exact:true}).selectOption('3');
  assert.equal(await page.locator('.assessment-row').count(),1);
  assert.match(await page.locator('.list-filter-summary').innerText(), /Showing 1 of 5[\s\S]*Week 3/);
  await page.reload(); await ready();
  assert.equal(await page.getByLabel('Teaching week', {exact:true}).inputValue(),'3');
  assert.equal(new URL(await page.locator('.assessment-row a').getAttribute('href'),base).searchParams.get('week'),'3');
  await page.getByLabel('Teaching week', {exact:true}).selectOption('1');
  assert.equal(await page.locator('.assessment-row').count(),0);
  assert.match(await page.locator('.agenda-empty').innerText(),/No assessments/);
  await page.getByLabel('Teaching week', {exact:true}).selectOption('undated');
  assert.match(await page.locator('.assessment-row').innerText(),/Undated presentation/);
  await page.getByRole('button',{name:'Clear filters',exact:true}).click();
  assert.equal(await page.locator('.assessment-row').count(),5);
  assert.equal(await page.getByLabel('Teaching week', {exact:true}).inputValue(),'');
  assert.equal(await page.getByRole('button',{name:'All modules',exact:true}).getAttribute('aria-pressed'),'true');
  assert.match(await page.locator('.assessment-row').first().innerText(),/Three-week project/);
  assert.match(await page.locator('.assessment-row').last().innerText(),/Undated presentation/);
  await page.screenshot({path:'/tmp/stackplan-list-desktop.png',fullPage:true});
  for (const width of [1024,768,600,390,320]) {
    await page.setViewportSize({width,height:900});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`List fits at ${width}px`);
  }
  await page.setViewportSize({width:390,height:844});
  await page.reload(); await ready();
  assert.equal(await page.locator('.topbar').count(),1);
  await page.screenshot({path:'/tmp/stackplan-list-mobile.png',fullPage:true});
  await page.getByRole('button', { name: 'All modules', exact: true }).click();
  await page.getByRole('button', { name: 'Calendar', exact: true }).click();
  for (const width of [1440, 1024, 768, 700, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `No horizontal page scroll at ${width}px`);
    assert.ok(await page.locator('.week-navigator').evaluate(element => element.scrollWidth <= element.clientWidth), `Calendar fits at ${width}px`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '/tmp/stackplan-calendar-mobile.png', fullPage: true });
  await page.getByRole('button',{name:'Week 13, 2 assessments',exact:true}).click();
  assert.equal(await page.locator('.week-tile.is-selected .calendar-week-button').evaluate(el=>el===document.activeElement),true,'Week selection focuses its calendar cell');
  assert.equal(await page.locator('.week-tile.is-selected .calendar-event').count(),2);
  // Existing saved trimesters and dense weeks retain every assessment.
  project.week_count = 6;
  items = Array.from({ length: 12 }, (_, index) => item(`dense-${index}`, `Assessment ${index + 1} with a long title <img src=x onerror=alert(1)>`, 3, 5));
  await page.goto(base); await ready();
  assert.equal(await page.locator('.week-tile').count(), 6);
  assert.equal(await page.locator('.calendar-event').count(), 12);
  assert.equal(await page.locator('.calendar-event img').count(), 0);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  items = [];
  await page.reload(); await ready();
  assert.equal(await page.locator('.calendar-event').count(), 0);
  assert.match(await page.locator('.module-filters').innerText(), /0 assessments/);
  assert.deepEqual(errors, []);
  console.log('PASS calendar, filtering, ranges, undated assessments, source links, saved selection, list, dense/empty weeks and responsive layouts');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
