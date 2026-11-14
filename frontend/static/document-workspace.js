import { request } from './api.js';
const $ = id => document.getElementById(id);
let project, active, documents = [], assessment, generation = 0, drawGeneration = 0;
const traces = new Map();
const originals = new Map();
window.addEventListener('pagehide', () => { for (const url of originals.values()) URL.revokeObjectURL(url); originals.clear(); });
function text(id, value) { $(id).textContent = value; }
function fail(message) { text('error', message); $('error').hidden = false; }
function busy(message) { text('status', message); $('status').hidden = !message; }
function sync(push = false) {
  const url = new URL(location.href);
  url.searchParams.set('project', project.id);
  if (assessment) url.searchParams.set('assessment', assessment.id); else url.searchParams.delete('assessment');
  url.searchParams.sort();
  if (push && url.href !== location.href) history.pushState(null, '', url); else history.replaceState(null, '', url);
  const back = new URLSearchParams({project:project.id,view:'schedule'});
  if (assessment) back.set('assessment',assessment.id);
  for (const key of ['layout','week','module']) if (url.searchParams.has(key)) back.set(key,url.searchParams.get(key));
  $('return-schedule').href = `/?${back}`;
}
async function trace(id) {
  if (!traces.has(id)) {
    if (traces.size >= 20) traces.delete(traces.keys().next().value);
    const pending = request(`/api/documents/${id}/trace`).catch(error => { traces.delete(id); throw error; });
    traces.set(id, pending);
  }
  return traces.get(id);
}
function missing(doc) {
  doc.unavailable = true;
  fail('Some original documents are unavailable. Your schedule and saved source text remain available.');
  text('canvas', 'Original unavailable. Saved source text remains available.');
  $('original').removeAttribute('href'); $('original').setAttribute('aria-disabled', 'true');
}
async function draw(doc, refs = [], page = 1) {
  const token = ++drawGeneration;
  text('canvas', 'Loading source…');
  text('source-precision', ''); $('source-precision').hidden = true;
  $('source-select').value = doc.id;
  $('original').removeAttribute('href'); $('original').setAttribute('aria-disabled', 'true');
  try {
    const source = await trace(doc.id);
    if (token !== drawGeneration) return;
    if (!source.original_available || doc.unavailable) { missing(doc); return; }
    const url = `/api/documents/${doc.id}/original`;
    $('original').href = url; $('original').removeAttribute('aria-disabled');
    const canvas = $('canvas'); canvas.replaceChildren();
    if (doc.media_type === 'application/pdf') {
      if (!originals.has(doc.id)) {
        const response = await fetch(url);
        if (token !== drawGeneration) return;
        if (!response.ok) { missing(doc); return; }
        const bytes = await response.blob();
        if (token !== drawGeneration) return;
        if (originals.size >= 3) { const oldest = originals.keys().next().value; URL.revokeObjectURL(originals.get(oldest)); originals.delete(oldest); }
        originals.set(doc.id, URL.createObjectURL(bytes));
      }
      const frame = document.createElement('iframe'); frame.className = 'pdf'; frame.title = `${doc.filename}, page ${page}`; frame.src = `${originals.get(doc.id)}#page=${page}`; canvas.append(frame);
      return; // Native PDF preview has no dependable page geometry for an overlay.
    }
    const coarse = refs.some(ref => (ref.regions || []).some(r => r.page === page && (r.granularity === 'table' || (!r.granularity && ref.context?.startsWith('table row;')))));
    if (coarse) { text('source-precision', 'This saved result can identify the table, but not the exact field location. Use the quoted source text below.'); $('source-precision').hidden = false; }
    const paper = document.createElement('div'); paper.className = 'paper';
    const image = document.createElement('img'); image.alt = doc.filename; image.src = url;
    image.onerror = () => { if (token === drawGeneration) missing(doc); };
    image.onload = () => {
      if (token !== drawGeneration || page !== 1 || !image.naturalWidth || !image.naturalHeight) return;
      const drawn = new Map();
      for (const ref of refs) for (const r of ref.regions || []) {
        const b = r.bbox;
        if (r.page !== 1 || r.coordinate_origin !== 'TOPLEFT' || !Array.isArray(b) || b.length !== 4 || !b.every(v => Number.isFinite(v) && v >= 0 && v <= 1) || b[0] >= b[2] || b[1] >= b[3]) continue;
        const context = r.role === 'column_header' || r.granularity === 'table' || (!r.granularity && ref.context?.startsWith('table row;')) || ref.context === `table row; header: ${ref.text}`;
        const key = b.join(':');
        if (drawn.has(key)) { if (context) drawn.get(key).classList.add('context-highlight'); continue; }
        const box = document.createElement('div'); box.className = `highlight${context ? ' context-highlight' : ''}`;
        Object.assign(box.style, {left:`${b[0]*100}%`,top:`${b[1]*100}%`,width:`${(b[2]-b[0])*100}%`,height:`${(b[3]-b[1])*100}%`}); paper.append(box); drawn.set(key, box);
      }
    };
    paper.append(image); canvas.append(paper);
  } catch (error) { if (token === drawGeneration) { fail(error.message); text('canvas', 'Source preview could not be loaded. Select a source to try again.'); } }
}
async function showEvidence(ids, button, primaryIds = ids) {
  const token = ++generation;
  for (const el of $('facts').children) { el.classList.toggle('selected', el === button); el.setAttribute('aria-pressed', String(el === button)); }
  text('source-text', 'Loading saved evidence…'); $('source-links').replaceChildren();
  try {
    // Source IDs do not encode document IDs. Resolve traces once, only for this selected module.
    const sources = ids.length ? await Promise.all(documents.map(doc => trace(doc.id))) : [];
    if (token !== generation) return;
    const elements = new Map(sources.flatMap(s => s.elements.map(e => [e.id, {...e, document_id:s.document_id}])));
    const refs = [...new Set(ids)].map(id => elements.get(id)).filter(Boolean);
    const primary = new Set(primaryIds);
    const isHeader = ref => (ref.regions || []).some(r => r.role === 'column_header') || ref.context === `table row; header: ${ref.text}`;
    // AI citations may include explanatory context; only the selected value drives overlays.
    const focused = refs.filter(ref => primary.has(ref.id) && !isHeader(ref));
    $('source-text').replaceChildren();
    if (!refs.length) text('source-text', 'No source evidence is recorded for this fact.');
    const links = new Set();
    for (const ref of refs) {
      const supporting = !primary.has(ref.id) || isHeader(ref);
      const p = document.createElement('p'); p.textContent = ref.text; p.dataset.evidenceRole = supporting ? 'supporting' : 'value';
      const citation = document.createElement('small'); citation.className = 'source-citation';
      const doc = documents.find(d => d.id === ref.document_id);
      const pages = [...new Set((ref.regions || []).map(r => r.page))];
      citation.textContent = `${supporting ? 'Supporting context · ' : ''}${doc?.filename || 'Source'}${pages.length ? ` · Page ${pages.join(', ')}` : ''}`; p.append(citation); $('source-text').append(p);
      for (const page of pages.length ? pages : [1]) {
        const key = `${doc.id}:${page}`; if (links.has(key)) continue; links.add(key);
        const b = document.createElement('button'); b.textContent = `${doc.filename} · Page ${page}`;
        b.onclick = () => draw(doc, focused.filter(r => r.document_id === doc.id), page); $('source-links').append(b);
      }
    }
    const first = focused[0] || refs[0]; const doc = documents.find(d => d.id === first?.document_id) || documents[0];
    if (doc) await draw(doc, focused.filter(r => r.document_id === doc.id), first?.regions?.[0]?.page || 1);
    else text('canvas', 'No source documents are registered for this module.');
  } catch (error) { if (token === generation) { text('source-text', 'Evidence could not be loaded. Select the fact to try again.'); fail(error.message); } }
}
function selectAssessment(id, push = true) {
  assessment = active.assessments.find(a => a.id === id) || active.assessments[0];
  $('facts').replaceChildren();
  if (!assessment) { text('assessment-title', 'No assessments found'); return; }
  sync(push); $('assessment-select').value = assessment.id;
  const f = assessment.facts; text('assessment-title', f.name);
  const fields = [ ['Assessment', f.name, ['name']], ['Due', f.week == null ? 'Week unknown' : (f.end_week == null || f.end_week === f.week) ? `Week ${f.week}` : `Weeks ${f.week}–${f.end_week}`, ['week','end_week']], ['Weight', f.weight_percent == null ? 'Weight unknown' : `${f.weight_percent}% ${f.weight_scope === 'module' ? 'of module' : f.weight_scope === 'group' ? 'of group' : '(scope unknown)'}`, ['weight_percent','weight_scope']] ];
  if (f.parent_key) fields.push(['Part of', f.parent_key, ['parent_key']]);
  if (f.kind === 'group') fields.push(['Type', 'Assessment group · contextual, not scheduled separately', ['kind']]);
  for (const [label, value, keys] of fields) {
    const b = document.createElement('button'); b.className = 'fact';
    const l = document.createElement('span'); l.className = 'fact-label'; l.textContent = label;
    const v = document.createElement('span'); v.className = 'fact-value'; v.textContent = value; b.append(l,v);
    b.dataset.field = keys[0];
    b.onclick = () => { const url = new URL(location.href); url.searchParams.set('field', keys[0]); url.searchParams.sort(); history.replaceState(null, '', url); return showEvidence([...new Set(keys.flatMap(k => assessment.evidence[k] || []))], b, keys.filter(k => k !== 'weight_scope').flatMap(k => assessment.evidence[k] || [])); }; $('facts').append(b);
  }
  const field = new URL(location.href).searchParams.get('field');
  ([...$('facts').children].find(button => button.dataset.field === field) || $('facts').firstElementChild).click();
}
async function selectModule(module, target, push = true) {
  const token = ++generation; ++drawGeneration;
  busy('Loading module evidence…'); $('details').hidden = true; text('canvas', 'Loading source…');
  try {
    const id = module.assessments[0]?.result_id;
    if (!id) { text('canvas', 'This module has no published assessments.'); busy(''); return; }
    const [result, docs] = await Promise.all([request(`/api/results/${id}`), request(`/api/results/${id}/documents`)]);
    if (token !== generation) return;
    active = result; documents = docs; text('module-title', module.module_title);
    $('assessment-select').replaceChildren(...result.assessments.map(a => new Option(a.facts.name, a.id)));
    $('source-select').replaceChildren(...docs.map(d => new Option(d.filename, d.id)));
    $('source-select').hidden = !docs.length; $('preview-title').hidden = !!docs.length;
    $('details').hidden = false; busy('');

    if (target && !result.assessments.some(a => a.id === target)) throw new Error('This assessment is unavailable. Return to the schedule and reload it.');
    selectAssessment(target, push);
  } catch (error) { if (token === generation) { busy(''); fail(error.message); } }
}
async function load() {
  const token = ++generation; ++drawGeneration; busy('Loading project…'); $('error').hidden = true; $('details').hidden = true;
  const params = new URL(location.href).searchParams;
  const id = params.get('project');
  if (!id) { location.replace('/?view=upload'); return; }
  try {
    const loaded = await request(`/api/projects/${id}`); if (token !== generation) return; project = loaded; assessment = null; sync();
    if (project.status !== 'Ready') {
      const message = `${project.name}: ${project.status}. No published schedule is available. ${(project.issues || []).map(i => i.message).join(' ')}`;
      fail(message); text('canvas', message); $('return-schedule').textContent = 'Back to project'; busy(''); return;
    }
    if (project.issues?.length) fail(project.issues.map(i => i.message).join(' '));
    const target = params.get('assessment');
    const module = target ? project.modules.find(m => m.assessments.some(a => a.id === target)) : project.modules[0];
    if (!module) { busy(''); if (target) throw new Error('This assessment is unavailable. Return to your schedule.'); text('canvas', 'No published modules.'); return; }
    await selectModule(module, target, false);
  } catch (error) { if (token === generation) { busy(''); fail(error.message); } }
}
$('assessment-select').onchange = () => selectAssessment($('assessment-select').value);
$('source-select').onchange = () => { ++generation; const doc = documents.find(d => d.id === $('source-select').value); if (doc) draw(doc); };
$('original').onclick = event => { if ($('original').getAttribute('aria-disabled') === 'true') event.preventDefault(); };
window.addEventListener('popstate', load);
load();
