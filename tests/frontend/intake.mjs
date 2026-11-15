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
  let writes = 0;
  const liveUrl = process.env.INTAKE_LIVE_URL;
  let staleLimits = !liveUrl;
  await page.route('**/api/**', async route => {
    if (liveUrl) {
      assert.equal(route.request().method(), 'GET', 'Live validation must not submit files');
      return route.continue();
    }
    if (route.request().method() !== 'GET') writes++;
    const path = new URL(route.request().url()).pathname;
    if (staleLimits && path === '/api/limits') return route.fulfill({json:{module_count:20,document_count:20,document_bytes:10485760,request_bytes:20971520}});
    await route.fulfill({ json: path === '/api/limits' ? { module_count:20, documents_per_module:10, document_bytes:10485760, request_bytes:20971520, project_name_length:150, module_title_length:200, credit:100, week_count:52, media_types:['application/pdf','image/png','image/jpeg'] } : [] });
  });
  await page.goto(liveUrl || `http://127.0.0.1:${server.address().port}/`);
  if (!liveUrl) {
    await page.getByRole('heading',{name:'Workspace could not be loaded'}).waitFor();
    assert.match(await page.getByRole('alert').innerText(),/Upload settings could not be loaded/);
    assert.equal(await page.locator('#module-images').count(),0,'Incomplete settings cannot enable upload');
    staleLimits = false;
    await page.getByRole('button',{name:'Reload saved results',exact:true}).click();
  }
  await page.getByRole('heading', {name:'Build your trimester'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Review documents',exact:true}).isDisabled(),true);
  async function checkDesktopFit() {
    for (const [width,height] of [[1440,900],[1366,768],[1280,720],[790,803]]) {
      await page.setViewportSize({width,height});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight+2), `No page scrolling at ${width}x${height}`);
      for(const selector of ['#trimester-name','.editor-actions button.primary','.build-schedule']) {
        assert.ok(await page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight;}), `${selector} is fully visible at ${width}x${height}`);
      }
    }
  }
  await checkDesktopFit();
  await page.setViewportSize({width:1280,height:720});
  await page.screenshot({path:'/tmp/stackplan-intake-desktop.png',fullPage:true});
  await page.locator('#trimester-name').fill('Year 1 · Trimester 1');
  for (const title of ['INF1103 · Programming Fundamentals','INF1104 · Computer Organisation']) {
    await page.getByLabel('Module title',{exact:true}).fill(title);
    await page.locator('#module-images').setInputFiles({name:'Assessment brief.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4 sample document')});
    await page.getByRole('button',{name:'Add module',exact:true}).click();
  }
  await page.getByRole('button',{name:'Review documents',exact:true}).click();
  await page.getByRole('heading',{name:'Everything in order?'}).waitFor();
  assert.equal(await page.locator('.submission-review article').count(),2);
  assert.equal(await page.locator('.review-file').count(),2);
  assert.match(await page.locator('.review-totals').innerText(),/Documents\s+2/);
  const url = await page.locator('.review-file').first().getAttribute('href');
  assert.match(url,/^blob:/);
  assert.match(await page.evaluate(async url => (await fetch(url)).text(),url),/%PDF-1.4/,'Preview preserves the selected original');
  assert.equal(await page.locator('#input-title').evaluate(el=>el===document.activeElement),true,'Review focuses heading before final action');
  await page.screenshot({path:'/tmp/stackplan-review-desktop.png',fullPage:true});
  for (const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:900});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Review fits ${width}px`);
  }
  await page.screenshot({path:'/tmp/stackplan-review-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Edit INF1103 · Programming Fundamentals',exact:true}).click();
  assert.equal(await page.locator('.screenshot-files li').count(),1);
  await page.getByLabel('Module title',{exact:true}).fill('INF1103 · Revised');
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.getByRole('button',{name:'Review documents',exact:true}).click();
  await page.getByRole('heading',{name:'INF1103 · Revised',exact:true}).waitFor();
  assert.equal(await page.locator('.review-file').first().getAttribute('href'),url,'Editing retains preview and file identity');
  await page.getByRole('button',{name:'Back to modules',exact:true}).click();
  await page.getByRole('button',{name:'Edit INF1103 · Revised',exact:true}).click();
  await page.getByRole('button',{name:'Remove this module from bucket',exact:true}).click();
  await page.getByRole('button',{name:'Undo removal',exact:true}).click();
  assert.equal(await page.locator('.bucket-card').count(),2);
  for (const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:900});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Intake fits ${width}px`);
  }
  await page.screenshot({path:'/tmp/stackplan-intake-mobile.png',fullPage:true});
  await page.setViewportSize({width:1280,height:720});
  for(let i=0;i<10;i++) {
    await page.getByLabel('Module title',{exact:true}).fill(`Extra module ${i}`);
    await page.locator('#module-images').setInputFiles({name:'Assessment.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4 sample')});
    await page.getByRole('button',{name:'Add module',exact:true}).click();
  }
  await checkDesktopFit();
  assert.ok(await page.locator('.bucket-content').evaluate(el=>el.scrollHeight>el.clientHeight),'Long module collections scroll internally');
  await page.getByLabel('Module title',{exact:true}).fill('Draft with many files');
  await page.locator('#module-images').setInputFiles(Array.from({length:8},(_,i)=>({name:`Source ${i}.pdf`,mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4 sample')})));
  await checkDesktopFit();
  assert.ok(await page.locator('.screenshot-files').evaluate(el=>el.scrollHeight>el.clientHeight),'Long selected-file lists scroll internally');
  await page.setViewportSize({width:1280,height:720});
  await page.screenshot({path:'/tmp/stackplan-intake-fit.png',fullPage:true});
  for(const [width,height] of [[390,700],[320,640],[1280,600]]) {
    await page.setViewportSize({width,height});
    assert.ok(await page.locator('.build-schedule').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight;}),'Review stays accessible on small/short screens');
  }

  assert.equal(writes,0,'Adding, editing, reviewing and previewing never submit files');
  assert.deepEqual(errors,[]);
  console.log('PASS intake, original previews, review totals, edit and undo file retention, focus, responsive layout, and no submissions before confirmation');
} finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
