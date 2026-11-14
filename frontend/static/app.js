import { ProcessingEvents } from './processing-events.js';
import { request } from './api.js?v=restricted-v2';
import { bucket, inputView, resetInput, configureInputLimits, handleInputAction, handleInputChange, addInputFiles, saveInputModule, showInputError } from './input-workspace.js?v=desktop-dark-2';
import { escape as e } from './html.js';
import { moduleColours } from './module-colours.js';

const JOB_POLL_INTERVAL_MS = 2000;
let operation = 0;
function assertCurrent(token) { if (token !== operation) throw new DOMException('Navigation changed', 'AbortError'); }
const app = document.querySelector('#app');
const state = { step: 'upload', projects: [], project: null, schedule: null, limits: null, busy: null, error: '', uncertain: false, submissionKey: null, progress: null };
const button = (label, action, extra = '', cls = '') => `<button type="button" data-action="${action}" class="${cls}" ${extra}>${label}</button>`;
const modules = () => state.project?.modules || [];
const processingStages = [
  ['queued', 'Queued', 'Waiting for processing to start.'],
  ['parsing', 'Read documents', 'Reading your documents.'],
  ['extracting', 'Find assessments', 'Extracting assessment facts.'],
  ['validating', 'Check sources', 'Checking facts and source evidence.'],
];
const documentStateLabels = {
  waiting: 'Waiting', parsing: 'Reading', extracting: 'Extracting', extracted: 'Extracted',
  failed: 'Failed', interrupted: 'Interrupted', not_processed: 'Not processed', unknown: 'Progress unavailable',
};
function documentProgressView(lastConfirmed = false) {
  const progress = state.progress;
  if (!progress?.documents?.length) return '';
  const unknown = progress.documents.some(doc => doc.state === 'unknown');
  const summary = unknown
    ? `${progress.extracted_documents} confirmed extracted · ${progress.total_documents} documents`
    : `${progress.extracted_documents} of ${progress.total_documents} documents extracted`;
  return `<section class="document-progress" aria-label="Document progress">
    <div class="document-progress-heading"><h2>${lastConfirmed ? 'Last confirmed progress' : 'Your documents'}</h2><span>${e(summary)}</span></div>
    <p class="document-progress-note">${lastConfirmed ? 'Status updates have stopped. Check submission status to refresh.' : 'Extracted documents still need final validation before the schedule is ready.'}</p>
    <ul class="document-progress-list" tabindex="0" aria-label="Document checklist">${progress.documents.map(doc => {
      const status = Object.hasOwn(documentStateLabels, doc.state) ? doc.state : 'unknown';
      const active = ['parsing', 'extracting'].includes(status);
      return `<li class="document-progress-item ${active ? 'is-active' : ''}" data-document-state="${status}" data-document-id="${e(doc.document_id)}">
        <span class="document-state-icon" aria-hidden="true">${status === 'extracted' ? '✓' : ['failed', 'interrupted'].includes(status) ? '!' : active ? '◉' : '○'}</span>
        <span class="document-progress-name"><strong>${e(doc.filename)}</strong><small>${e(doc.module_title)}</small></span>
        <span class="document-state-label">${documentStateLabels[status]}</span>
      </li>`;
    }).join('')}</ul>
  </section>`;
}
function waiting({ label, screen = false, detail = '', stage = '' }) {
  const processing = state.step === 'processing';
  const message = detail || 'This will update automatically when your workspace is ready.';
  const loader = '<div class="loader-stack" aria-hidden="true"><i></i><i></i><i></i></div>';
  const progress = '<div class="loading-track" aria-hidden="true"><span></span></div>';
  if (screen || processing) {
    const current = processingStages.findIndex(([key]) => key === stage);
    const stages = processing ? `<ol class="processing-stages" aria-label="Processing stages">${processingStages.map(([key, title], index) => `<li class="${index === current ? 'is-current' : ''}" ${index === current ? 'aria-current="step"' : ''}><span class="stage-marker" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span><span>${title}</span></li>`).join('')}</ol>` : '';
    return `<section class="processing-screen" data-loading aria-label="${e(label)}"><div class="processing-panel">
      <div class="processing-brand">${loader}<span>stackplan</span></div>
      <div class="processing-copy"><p class="eyebrow">${processing ? 'FROM DOCUMENTS TO A CLEARER WEEK' : 'YOUR WORKSPACE'} </p><h1>${processing ? 'Making room for the work ahead.' : e(label)}</h1><p>${processing ? 'We’re turning your module documents into one assessment schedule, with every fact linked to its source.' : e(message)}</p></div>
      ${stages}<div class="processing-live" role="status" aria-live="polite" aria-atomic="true"><span class="status-dot" aria-hidden="true"></span><span>${e(processing ? message : label)}</span></div>${progress}${processing ? documentProgressView() : ''}
      <p class="processing-note">${processing ? 'Your submission is saved. Your schedule will appear here when it’s ready.' : 'You can keep this page open.'}</p>
    </div><p class="processing-signoff">Plan the work. See the source.</p></section>`;
  }
  return `<section class="request-status" data-loading role="status" aria-live="polite" aria-label="${e(label)}">${loader}<div><strong>${e(label)}</strong><p>${e(message)}</p></div>${progress}</section>`;
}
let scheduleColours = new Map();
const moduleStyle = id => scheduleColours.get(id) || '';
function scheduleParams() {
  const params = new URL(location.href).searchParams;
  return { layout: params.get('layout') === 'list' ? 'list' : 'timeline', week: params.get('week') || '', module: params.get('module') || '' };
}
function scheduleWeekLabel(item) {
  if (item.week == null) return 'Not dated';
  return !item.end_week || item.end_week === item.week ? `Week ${item.week}` : `Weeks ${item.week}–${item.end_week}`;
}
function scheduleWeightLabel(item) {
  if (item.weight_percent == null) return 'Weight unknown';
  return `${item.weight_percent}% ${item.weight_scope === 'module' ? 'of module' : item.weight_scope === 'group' ? 'of group' : '(scope unknown)'}`;
}
function sourceItem(item, calendar = false) {
  const params = new URLSearchParams({project: state.project.id, assessment: item.assessment_id});
  const selection = scheduleParams();
  for (const key of ['layout','week','module']) if (selection[key]) params.set(key, selection[key]);
  const content = calendar
    ? `<span class="calendar-module">${e(item.module_title)}</span><span class="calendar-event-name">${e(item.name)}</span><span class="calendar-event-meta">${e(scheduleWeightLabel(item))}${item.end_week > item.week ? ` · ${scheduleWeekLabel(item)}` : ''}</span>`
    : `${e(item.name)}<span aria-hidden="true">↗</span>`;
  return `<a class="milestone${calendar ? ' calendar-event' : ''}" style="${moduleStyle(item.module_id)}" data-document-preview href="/documents?${e(params)}" aria-label="${e(item.name)} — open source traceability">${content}</a>`;
}
function scheduleView() {
  const selection = scheduleParams();
  const weeks = state.schedule?.weeks || [];
  const unscheduled = state.schedule?.unscheduled || [];
  const unique = items => [...new Map(items.map(item => [item.assessment_id, item])).values()];
  const all = unique([...weeks.flatMap(week => week.items), ...unscheduled]).sort((a, b) => (a.week ?? Infinity) - (b.week ?? Infinity));
  scheduleColours = moduleColours([...modules().map(module => module.id), ...all.map(item => item.module_id)]);
  const inModule = item => !selection.module || item.module_id === selection.module;
  const filtered = all.filter(inModule);
  const undatedCount = unique(unscheduled.filter(inModule)).length;
  const weekData = weeks.find(week => String(week.week) === selection.week);
  const visible = unique(selection.week === 'undated' ? unscheduled : weekData ? weekData.items : all).filter(inModule);
  const showAgenda = selection.layout === 'list' || Boolean(selection.week);
  const weekMap = `<section class="term-map" aria-label="Whole trimester" ${selection.layout === 'list' ? 'hidden' : ''}>
    <div class="term-caption"><div><h2>Trimester calendar</h2><p>Weeks 1–${state.project.week_count}</p></div><p>Open an assessment to view its source.</p></div>
    <div class="week-navigator">${weeks.map(week => {
      const items = unique(week.items.filter(inModule));
      const selected = selection.week === String(week.week);
      return `<section class="week-tile${items.length ? ' has-assessments' : ''}${selected ? ' is-selected' : ''}" aria-label="Week ${week.week}">
        ${button(`<span class="week-heading">Week <strong>${week.week}</strong></span>${items.length ? `<span class="week-count" aria-hidden="true">${items.length}</span>` : ''}`, 'schedule-week', `data-week="${week.week}" aria-label="Week ${week.week}, ${items.length} assessments" aria-pressed="${selected}"`, 'calendar-week-button')}
        <div class="calendar-events">${items.map(item => sourceItem(item, true)).join('')}</div>
      </section>`;
    }).join('')}</div>
    <div class="calendar-footer"><p>Organised by teaching week. Assessments spanning several weeks appear in each week.</p>${undatedCount ? button(`Undated · ${undatedCount}`, 'schedule-week', 'data-week="undated" aria-label="Undated"', 'text-button') : ''}</div>
  </section>`;
  const agenda = `<section class="assessment-agenda schedule-list" aria-label="Assessments by due week" ${showAgenda ? '' : 'hidden'}>
    <div class="agenda-heading"><h2>${selection.week === 'undated' ? 'Undated assessments' : weekData ? `Week ${weekData.week}` : 'All assessments'} <span>${visible.length}</span></h2><div>${undatedCount && selection.layout === 'list' && selection.week !== 'undated' ? button('Undated', 'schedule-week', 'data-week="undated"', 'text-button') : ''}${selection.week ? button('Show all weeks', 'schedule-week', 'data-week=""', 'text-button') : ''}</div></div>
    <div class="agenda-table"><div class="agenda-columns" aria-hidden="true"><span>Due</span><span>Module</span><span>Assessment</span><span>Weight</span></div>${visible.map(item => `<article class="assessment-row" style="${moduleStyle(item.module_id)}"><span class="due-label">${scheduleWeekLabel(item)}</span><span class="module-label">${e(item.module_title)}</span>${sourceItem(item)}<span class="weight-label">${scheduleWeightLabel(item)}</span></article>`).join('') || '<p class="agenda-empty">No assessments '+(selection.week ? 'in this week or selection.' : 'have been published.')+'</p>'}</div>
  </section>`;
  return `<div class="page-heading"><div><p class="eyebrow">${e(state.project.name)} · ${state.project.week_count} weeks</p><h1>Your assessment schedule</h1></div><div class="view-switch" role="group" aria-label="Schedule view">${button('Calendar', 'schedule-layout', `data-layout="timeline" aria-pressed="${selection.layout === 'timeline'}"`)}${button('List', 'schedule-layout', `data-layout="list" aria-pressed="${selection.layout === 'list'}"`)}</div></div>
    <div class="module-filters" role="group" aria-label="Filter modules">${button('All modules', 'schedule-module', `data-module="" aria-pressed="${!selection.module}"`)}${modules().map(module => button(`<span class="module-swatch" aria-hidden="true"></span>${e(module.module_title)}`, 'schedule-module', `style="${moduleStyle(module.id)}" data-module="${e(module.id)}" aria-pressed="${selection.module === module.id}"`)).join('')}<span role="status">${filtered.length} assessment${filtered.length === 1 ? '' : 's'}</span></div>
    ${weekMap}${agenda}`;
}

function terminalView() {
  const project = state.project;
  return `<section class="processing-issue terminal-failure" role="alert"><div class="issue-icon" aria-hidden="true">!</div><div class="issue-copy"><p class="issue-kicker">${e(project.name)} · ${e(project.status)}</p><h1>${project.status === 'Interrupted' ? 'Processing was interrupted' : 'We could not finish processing'}</h1><p>No schedule was published. Submit corrected or additional documents in a new trimester.</p><ul>${(project.issues || []).map(issue => `<li><strong>${e(modules().find(m => m.id === issue.module_id)?.module_title || 'Trimester')}</strong><span>${e(issue.message)}${issue.document_id ? ` · Document ${e(issue.document_id)}` : ''}</span></li>`).join('')}</ul>${documentProgressView()}<div class="issue-actions">${button('Create new trimester', 'restart', '', 'primary')}</div></div></section>`;
}
function sourceIssue() {
  const issues = state.project?.issues || [];
  if (!issues.length) return '';
  return `<section class="processing-issue source-issue" role="region" aria-label="Source availability"><div class="issue-icon" aria-hidden="true">!</div><div class="issue-copy"><p class="issue-kicker">Source availability</p><h2>Some original documents are unavailable</h2><p>The complete schedule and saved source text remain available.</p><ul>${issues.map(issue => `<li><strong>${e(modules().find(m => m.id === issue.module_id)?.module_title || 'Module')}</strong><span>${e(issue.message)}</span></li>`).join('')}</ul></div></section>`;
}
function feedbackView() {
  return `<div class="feedback-stack" aria-label="Errors and warnings">${state.step === 'schedule' ? sourceIssue() : ''}${state.error ? `<div class="message error" role="alert"><p>${e(state.error)}</p>${state.uncertain && state.project ? button('Check submission status', 'recover') : button('Reload saved results', 'reload')}</div>` : ''}</div>`;
}
function render() {
  document.body.classList.toggle('input-page', state.step !== 'schedule');
  document.body.classList.toggle('schedule-page', state.step === 'schedule');
  const select = document.querySelector('#project-picker');
  select.innerHTML = `<option value="">Open a saved trimester</option>${state.projects.map(p => `<option value="${p.id}" ${p.id === state.project?.id ? 'selected' : ''}>${e(p.name)}</option>`).join('')}`;
  document.querySelectorAll('[data-step]').forEach(el => {
    if (el.dataset.step === state.step) el.setAttribute('aria-current', 'step'); else el.removeAttribute('aria-current');
  });
  const content = !state.limits ? waiting({ label: 'Opening your workspace…', screen: true })
    : state.step === 'upload' ? inputView(state.project)
    : state.step === 'schedule' ? scheduleView()
    : state.step === 'failure' ? terminalView()
    : '<section class="processing-context" aria-label="Document processing"></section>';
  app.innerHTML = `<main id="main" tabindex="-1">${content}${feedbackView()}</main>`;
  showBusy();
  const selected = new URL(location.href).searchParams.get('assessment');
  if (selected) [...document.querySelectorAll('[data-document-preview]')].find(a => a.getClientRects().length && new URL(a.href).searchParams.get('assessment') === selected)?.focus({preventScroll:true});
}
function showBusy() {
  document.querySelector('[data-busy]')?.remove();
  if (state.busy) {
    if (!state.limits) app.querySelector('#main > [data-loading]:not([data-busy])')?.remove();
    const processingContext = app.querySelector('.processing-context');
    if (processingContext) processingContext.replaceChildren();
    const target = processingContext || app.querySelector('#main') || app;
    target.insertAdjacentHTML('beforeend', waiting(state.busy).replace('data-loading', 'data-loading data-busy'));
  }
  const context = app.querySelector('.processing-context');
  if (context && !state.busy && state.error) context.innerHTML = '<h1>Processing status unavailable</h1><p>Your submission may still be processing. Check its status below before submitting again.</p>' + documentProgressView(true);
  // Keep the live status outside a busy region so stage changes are announced.
  app.querySelector('.input-workspace')?.setAttribute('aria-busy', String(Boolean(state.busy)));
  app.querySelectorAll('button, input, select').forEach(el => { el.disabled = Boolean(state.busy) || (state.uncertain && el.dataset.action !== 'recover' && el.dataset.action !== 'restart') || el.dataset.disabled === 'true'; });
  document.querySelector('#project-picker').disabled = Boolean(state.busy);
  document.querySelector('#new-project').disabled = Boolean(state.busy);
  document.querySelectorAll('.workflow-steps button').forEach(el => {
    el.disabled = Boolean(state.busy) || (el.dataset.action === 'schedule' && state.project?.status !== 'Ready');
  });
}
function syncUrl(push = false) {
  const url = new URL(location.href);
  if (state.project) { url.searchParams.set('project', state.project.id); url.searchParams.set('view', state.step); }
  else { url.searchParams.delete('project'); url.searchParams.set('view', 'upload'); }
  if (!state.project) for (const key of ['assessment','week','module','layout']) url.searchParams.delete(key);
  url.hash = '';
  if (push && url.href !== location.href) history.pushState(null, '', url); else history.replaceState(null, '', url);
}
function selectProject(project) {
  if (state.project && state.project.id !== project.id) {
    const url = new URL(location.href);
    for (const key of ['week','module','assessment']) url.searchParams.delete(key);
    history.replaceState(null,'',url);
  }
  if (state.project?.id !== project.id) state.progress = null;
  state.project = project; state.schedule = project.schedule;
  state.step = project.status === 'Created' ? 'upload' : project.status === 'Ready' ? 'schedule' : ['Failed', 'Interrupted'].includes(project.status) ? 'failure' : 'processing';
  if (project.status !== 'Created') resetInput();
}
async function waitForVisiblePage() {
  if (!document.hidden) return;
  await new Promise(resolve => {
    const resume = () => {
      if (document.hidden) return;
      document.removeEventListener('visibilitychange', resume);
      resolve();
    };
    document.addEventListener('visibilitychange', resume);
  });
}
async function waitForJob(jobId, projectId, token) {
  const updates = new ProcessingEvents(projectId);
  try {
    while (true) {
      await waitForVisiblePage();
      assertCurrent(token);
      const job = await request(`/api/jobs/${jobId}`);
      assertCurrent(token);
      const progressChanged = JSON.stringify(state.progress) !== JSON.stringify(job.progress || null);
      state.progress = job.progress || null;
      if (!['queued', 'running'].includes(job.status)) return job;
      const activeDocument = state.progress?.documents?.find(doc => ['parsing', 'extracting'].includes(doc.state));
      const stageDetail = processingStages.find(([key]) => key === job.stage)?.[2] || 'Processing your documents…';
      const activity = activeDocument
        ? `${activeDocument.state === 'parsing' ? 'Reading' : 'Extracting assessments from'} ${activeDocument.filename}`
        : stageDetail;
      const detail = state.progress && !state.progress.documents.some(doc => doc.state === 'unknown')
        ? `${activity} · ${state.progress.extracted_documents} of ${state.progress.total_documents} documents extracted`
        : activity;
      if (state.busy && (state.busy.detail !== detail || state.busy.stage !== job.stage || progressChanged)) {
        state.busy.detail = detail;
        state.busy.stage = job.stage;
        showBusy();
      }
      await updates.wait(JOB_POLL_INTERVAL_MS);
    }
  } finally {
    updates.close();
  }
}
async function refreshProject(id) {
  const token = operation;
  const project = await request(`/api/projects/${id}`); assertCurrent(token); selectProject(project);
  if (state.project.status === 'Processing') {
    state.busy = { label: 'Processing your documents…', detail: 'Your submission is saved. Checking processing status…' };
    render(); await waitForJob(state.project.job_id, id, token);
    const terminal = await request(`/api/projects/${id}`); assertCurrent(token); selectProject(terminal);
  } else if (['Failed', 'Interrupted'].includes(project.status) && project.job_id) {
    const job = await request(`/api/jobs/${project.job_id}`); assertCurrent(token); state.progress = job.progress || null;
  }
}
async function run(label, action, options = {}) {
  if (state.busy) return;
  const token = ++operation;
  state.busy = { label, ...options }; state.error = ''; state.uncertain = false; showBusy();
  try { await action(); assertCurrent(token); syncUrl(); render(); }
  catch (error) {
    if (token !== operation || error.name === 'AbortError') return;
    state.error = error.message;
    state.uncertain = Boolean(state.project && (error.uncertain || error.issues?.some(i => i.code === 'project_frozen') || state.project.status === 'Processing'));
    if (!state.project && error.uncertain) state.error += ' If project creation succeeded, an unused project may appear in the saved list. The API cannot recover creation by name.';
    if (!state.limits) { document.querySelector('#main [data-loading]')?.remove(); document.querySelector('#main').insertAdjacentHTML('afterbegin', '<h1>Workspace could not be loaded</h1>'); }
    let alert = document.querySelector('.message.error');
    if (!alert) { document.querySelector('.feedback-stack').insertAdjacentHTML('beforeend', '<div class="message error" role="alert"></div>'); alert = document.querySelector('.message.error'); }
    alert.innerHTML = `<p>${e(state.error)}</p>${state.uncertain ? button('Check submission status', 'recover') : button('Reload saved results', 'reload')}`;
  } finally { if (token === operation) { state.busy = null; showBusy(); } }
}
async function loadSaved() {
  const token = operation;
  const limits = await request('/api/limits'); assertCurrent(token); state.limits = limits; configureInputLimits(limits);
  const projects = await request('/api/projects'); assertCurrent(token); state.projects = projects;
  const id = new URL(location.href).searchParams.get('project');
  if (id) await refreshProject(id); else { state.project = null; state.schedule = null; state.progress = null; state.step = 'upload'; }
}
function startNew() {
  state.project = null; state.schedule = null; state.step = 'upload'; state.progress = null; state.submissionKey = null; state.error = ''; state.uncertain = false; resetInput(); syncUrl(true); render();
}
async function buildSchedule() {
  if (state.project && state.project.status !== 'Created' || state.uncertain) return;
  const nameField = document.querySelector('#trimester-name'); if (!nameField.reportValidity()) return;
  let submission;
  try { submission = bucket.submission(); } catch (error) { showInputError(error.message); return; }
  await run('Uploading your documents…', async () => {
    const token = operation;
    try {
      if (!state.project) {
        const created = await request('/api/projects', { method: 'POST', body: { name: submission.name, week_count: Number(bucket.weekCount) } });
        assertCurrent(token); state.project = created;
        syncUrl(); nameField.readOnly = true;
      }
      state.submissionKey ||= crypto.randomUUID();
      const accepted = await request(`/api/projects/${state.project.id}/process`, { method: 'POST', body: submission.upload, headers: { 'Idempotency-Key': state.submissionKey } });
      assertCurrent(token);
      if (!accepted.job_id) { const error = new Error('Acceptance could not be confirmed. Check submission status.'); error.uncertain = true; throw error; }
      state.busy = { label: 'Processing your documents…', detail: 'Your submission is saved. Checking processing status…' };
      state.progress = null;
      state.project = { ...state.project, status: 'Processing', job_id: accepted.job_id }; state.step = 'processing'; resetInput(); render();
      await refreshProject(state.project.id); const projects = await request('/api/projects'); assertCurrent(token); state.projects = projects; syncUrl(true);
    } catch (error) {
      if (token !== operation) throw error;
      if (state.project?.status === 'Created' && error.status && error.status < 500) state.submissionKey = null;
      throw error;
    }
  }, { detail: 'Uploading and checking acceptance. Keep this tab open.' });
}
document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]'); if (!target || state.busy) return;
  const action = target.dataset.action;
  if (['schedule-layout','schedule-week','schedule-module'].includes(action)) {
    const key = action.replace('schedule-', '');
    const value = target.dataset[key];
    const url = new URL(location.href); value ? url.searchParams.set(key,value) : url.searchParams.delete(key);
    url.searchParams.delete('assessment'); history.replaceState(null,'',url); render();
    [...document.querySelectorAll(`[data-action="${action}"]`)].find(el => el.dataset[key] === value)?.focus({preventScroll:true}); return;
  }
  if (action === 'restart' || action === 'upload') { startNew(); return; }
  if (state.step === 'upload' && handleInputAction(target, render)) return;
  if (action === 'build-schedule') await buildSchedule();
  if (action === 'recover') await run('Checking submission status…', async () => { await refreshProject(state.project.id); if (state.project.status === 'Created') { state.uncertain = true; state.error = 'No acceptance is recorded yet. Keep checking status, or start a new trimester. This submission will not be resent.'; } });
  if (action === 'reload') await run('Loading saved results…', loadSaved);
  if (action === 'schedule' && state.project?.status === 'Ready') { state.step = 'schedule'; syncUrl(true); render(); }
});
document.querySelector('#project-picker').onchange = async event => {
  if (!event.target.value) return;
  await run('Loading assessments…', async () => { await refreshProject(event.target.value); syncUrl(true); });
};
document.addEventListener('input', event => { if (state.step === 'upload' && !state.busy) handleInputChange(event); });
document.addEventListener('change', event => {
  if (event.target.id === 'module-images' && !state.busy) { addInputFiles(event.target.files); event.target.value = ''; }
});
for (const type of ['dragenter', 'dragover', 'dragleave', 'drop']) document.addEventListener(type, event => {
  const drop = event.target.closest('#screenshot-drop'); if (!drop) return; event.preventDefault(); if (state.busy) return;
  if (type === 'dragenter' || type === 'dragover') drop.classList.add('is-dragging');
  if (type === 'dragleave' && !drop.contains(event.relatedTarget)) drop.classList.remove('is-dragging');
  if (type === 'drop') { drop.classList.remove('is-dragging'); addInputFiles(event.dataTransfer.files); }
});
document.addEventListener('submit', event => { if (event.target.id === 'module-form') { event.preventDefault(); if (!state.busy) saveInputModule(render); } });
window.addEventListener('beforeunload', event => { if (state.step === 'upload' && (bucket.entries.length || bucket.hasDraft)) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('popstate', () => { operation++; state.busy = null; run('Loading saved view…', loadSaved); });
render(); run('Opening your workspace…', loadSaved, { screen: true });

// Store the selected assessment in the schedule URL before navigating to its source.
document.addEventListener('click', event => {
  const item = event.target.closest('[data-document-preview]');
  if (!item) return;
  const url = new URL(location.href);
  url.searchParams.set('assessment', new URL(item.href).searchParams.get('assessment'));
  history.replaceState(null, '', url);
});
