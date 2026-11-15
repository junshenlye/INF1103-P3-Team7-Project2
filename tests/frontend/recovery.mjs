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
  let status = 'Partial', revision = 1, generation = 1, retryPosts = 0, replacementPosts = 0, failPoll = false, loseReplacement = false;
  const docs = () => [
    {document_id:'good',module_id:'m1',module_title:'HSC1007',filename:'HSC1007.jpeg',state:'extracted',execution:'succeeded',inference:'understood',generation:1,retryable:false,issues:[]},
    {document_id:'bad',module_id:'m2',module_title:'HTM2211',filename:'HTM2211.jpg',state:status==='Processing'?'extracting':status==='Ready'?'extracted':'failed',execution:status==='Processing'?'running':status==='Ready'?'succeeded':'failed',inference:status==='Ready'?'understood':'unknown',generation,retryable:status==='Partial',issues:[]}
  ];
  const project = () => ({id:'recovery',name:'Recovery test',week_count:14,status,job_id:'job',coverage:status==='Ready'?'complete':'partial',schedule_revision_id:revision,stale:replacementPosts>0 && status!=='Ready',documents:docs(),modules:[{id:'m1',module_title:'HSC1007'},{id:'m2',module_title:'HTM2211'}],issues:[],schedule:{weeks:[{week:1,items:[{assessment_id:'a1',module_id:'m1',module_title:'HSC1007',name:'Saved assessment',week:1,weight_percent:30,weight_scope:'module'}]}],unscheduled:[]}});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/events')) return route.fulfill({contentType:'text/event-stream',body:': keep-alive\n\n'});
    if(path.endsWith('/retry')) {
      retryPosts++; assert.equal(route.request().postDataJSON().expected_generation,generation);
      assert.ok(route.request().headers()['idempotency-key']); generation++; status='Processing';
      return route.fulfill({status:202,json:{job_id:'job',document_id:'bad',generation}});
    }
    if(path.endsWith('/replacement')) {
      replacementPosts++;
      assert.equal(route.request().postData(),'replacement bytes');
      assert.equal(route.request().headers()['expected-generation'],String(generation));
      assert.equal(decodeURIComponent(route.request().headers()['x-filename']),'Clear source.pdf');
      status='Processing';generation++;
      if(loseReplacement) return route.abort();
      return route.fulfill({status:202,json:{job_id:'job',document_id:'bad',generation}});
    }
    assert.equal(route.request().method(),'GET');
    if(path.includes('/jobs/')) return failPoll ? route.fulfill({status:503,json:{issues:[{message:'Status connection interrupted'}]}}) : route.fulfill({json:{id:'job',status:status==='Processing'?'running':status,stage:'extracting',progress:{documents:docs(),extracted_documents:1,total_documents:2}}});
    return route.fulfill({json:path==='/api/limits'?{module_count:20,documents_per_module:10,document_bytes:10485760,request_bytes:52428800,project_name_length:150,module_title_length:200,credit:100,week_count:52,media_types:['application/pdf','image/png','image/jpeg']}:path==='/api/projects'?[project()]:project()});
  });
  const base=`http://127.0.0.1:${server.address().port}/?project=recovery&week=1`;
  await page.goto(base);
  await page.getByRole('heading',{name:'Your assessment schedule',exact:true}).waitFor();
  await page.locator('.recovery-disclosure > summary').click();
  assert.equal(await page.getByRole('button',{name:'Retry document',exact:true}).count(),1);
  assert.equal(await page.locator('[data-document-id="good"] input').count(),0,'Successful documents need no replacement control');
  await page.getByRole('button',{name:'Retry document',exact:true}).click();
  await page.locator('.recovery-status').filter({hasText:'Processing'}).waitFor();
  assert.equal(retryPosts,1);
  assert.equal(await page.locator('.processing-screen').count(),0,'No full-screen loader over partial calendar');
  assert.equal(await page.getByRole('button',{name:'List',exact:true}).isEnabled(),true);
  await page.getByRole('button',{name:'List',exact:true}).click();
  failPoll=true;
  await page.getByRole('button',{name:'Check submission status',exact:true}).waitFor();
  assert.equal(await page.getByRole('heading',{name:'Your assessment schedule',exact:true}).isVisible(),true);
  failPoll=false;status='Partial';
  await page.getByRole('button',{name:'Check submission status',exact:true}).click();
  await page.getByRole('button',{name:'Retry document',exact:true}).waitFor();
  const replacement={name:'Clear source.pdf',mimeType:'application/pdf',buffer:Buffer.from('replacement bytes')};
  await page.getByLabel('Replace HTM2211.jpg',{exact:true}).setInputFiles(replacement);
  await page.getByRole('button',{name:'Upload replacement',exact:true}).waitFor();
  assert.equal(replacementPosts,0,'File selection does not upload');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  assert.equal(replacementPosts,0);
  await page.getByLabel('Replace HTM2211.jpg',{exact:true}).setInputFiles(replacement);
  loseReplacement=true;
  await page.getByRole('button',{name:'Upload replacement',exact:true}).click();
  await page.getByRole('button',{name:'Check submission status',exact:true}).waitFor();
  assert.equal(replacementPosts,1,'Uncertain replacement is not automatically resent');
  await page.getByRole('button',{name:'Check submission status',exact:true}).click();
  await page.locator('.recovery-status').filter({hasText:'Processing'}).waitFor();
  assert.match(await page.locator('.coverage-heading').innerText(),/out of date/);
  assert.equal(await page.locator('.replacement-review').count(),0,'Status recovery clears a replacement already accepted');
  await page.screenshot({path:'/tmp/stackplan-recovery-desktop.png',fullPage:true});
  for(const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:900});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Recovery fits ${width}`);
  }
  status='Ready';revision++;
  await page.locator('.coverage-notice').waitFor({state:'detached'});
  assert.equal(new URL(page.url()).searchParams.get('week'),'1');
  assert.equal(new URL(page.url()).searchParams.get('layout'),'list');
  assert.equal(await page.locator('.assessment-row').count(),1,'Saved assessment remains without duplicates');
  assert.equal(replacementPosts,1);
  assert.deepEqual(errors,[]);
  console.log('PASS partial calendar, targeted retry, usable filters while processing, status recovery, replacement confirmation/cancel, raw file body, uncertain acceptance, stale warning, responsive layout and preserved view');
} finally { if(browser) await browser.close(); await new Promise(resolve=>server.close(resolve)); }
