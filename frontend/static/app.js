import { ProcessingEvents } from './processing-events.js';
import { request } from './api.js?v=recovery-1';
import { bucket, inputView, resetInput, configureInputLimits, handleInputAction, handleInputChange, addInputFiles, saveInputModule, showInputError } from './input-workspace.js?v=intake-fit-1';
import { escape as e } from './html.js';
import { moduleColours } from './module-colours.js?v=2';

const JOB_POLL_INTERVAL_MS = 2000;
let operation = 0;
function assertCurrent(token) { if (token !== operation) throw new DOMException('Navigation changed', 'AbortError'); }
const app = document.querySelector('#app');
const state = { step: 'upload', projects: [], project: null, schedule: null, limits: null, busy: null, error: '', uncertain: false, submissionKey: null, progress: null };
const button = (label, action, extra = '', cls = '') => `<button type="button" data-action="${action}" class="${cls}" ${extra}>${label}</button>`;
const modules = () => state.project?.modules || [];
const loadingVisual = '<div class="loading-documents" aria-hidden="true"><i class="paper paper-back"></i><i class="paper paper-front"><span></span><span></span><span></span><b></b></i><i class="scan-line"></i></div>';
function processingFeedback(stage, documents) {
  if (stage === 'complete') return 'Opening your schedule';
  if (stage === 'finishing') return 'All checks complete';
  if (stage === 'uploading') return 'Sending your documents';
  if (stage === 'queued') return 'Waiting to start';
  if (stage === 'validating') return 'Checking sources';
  const reading = documents.some(doc => doc.state === 'parsing');
  const extracting = documents.some(doc => doc.state === 'extracting');
  const activity = reading && extracting ? 'Reading & extracting' : reading || stage === 'parsing' ? 'Reading documents'
    : extracting || stage === 'extracting' ? 'Extracting assessments' : stage ? 'Processing documents' : 'Starting processing';
  const known = documents.length > 0 && documents.every(doc => ['waiting', 'parsing', 'extracting', 'extracted'].includes(doc.state));
  return known ? `${activity} · ${documents.filter(doc => doc.state === 'extracted').length}/${documents.length} processed` : activity;
}
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
  const message = detail || 'Loading your saved workspace.';
  if (screen || processing) {
    const submitting = stage === 'uploading', complete = stage === 'complete';
    const documents = state.progress?.documents || [];
    const processed = stage === 'validating' || (documents.length > 0 && documents.every(doc => doc.state === 'extracted'));
    const done = complete ? 3 : submitting ? 0 : processed ? 2 : 1;
    const title = complete ? 'Your schedule is ready.' : submitting ? 'Sending your documents…' : processing ? 'Building your schedule…' : label;
    const check = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4 4 10-10"/></svg>';
    const steps = [
      ['Upload documents', 'Documents received'],
      ['Read assessments', 'Assessments extracted'],
      ['Prepare schedule', 'Schedule ready'],
    ];
    const checkpoints = processing || submitting || complete
      ? `<ol class="checkpoint-list" aria-label="Schedule progress">${steps.map(([pending, finished], index) => `<li class="${index < done ? 'is-done' : index === done ? 'is-active' : ''}" ${index === done ? 'aria-current="step"' : ''}><span class="checkpoint-marker" aria-hidden="true">${check}<span class="checkpoint-dot">${index + 1}</span></span><span class="checkpoint-label">${index < done ? finished : pending}</span><span class="checkpoint-state">${index < done ? 'Complete' : index === done ? (stage === 'queued' ? 'Queued' : 'In progress') : 'Waiting'}</span></li>`).join('')}</ol>` : '';
    const note = complete ? 'Opening your schedule now.' : submitting ? 'Keep this tab open until your documents are received.' : processing ? 'We’ll open your schedule automatically when it’s ready.' : '';
    return `<section class="processing-screen ${complete ? 'is-complete' : ''}" data-loading aria-label="${e(title)}"><div class="loading-wordmark" aria-hidden="true"><span class="brand-icon"><i></i><i></i><i></i></span>stackplan</div><div class="processing-panel">
      <div class="processing-visual">${loadingVisual}<span class="completion-check">${check}</span></div>
      <div class="processing-copy" role="status" aria-live="polite" aria-atomic="true"><h1>${e(title)}</h1><p class="processing-detail">${e(processing || submitting || complete ? processingFeedback(stage, documents) : message)}</p></div>
      ${checkpoints}
      <p class="processing-footnote">${e(note)}</p>
    </div></section>`;
  }
  return `<section class="request-status" data-loading role="status" aria-live="polite" aria-label="${e(label)}"><div class="loader-stack" aria-hidden="true"><i></i><i></i><i></i></div><div><strong>${e(label)}</strong><p>${e(message)}</p></div></section>`;
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
    ? `<span class="calendar-module">${e(item.module_title)}</span><span class="calendar-event-name">${e(item.name)}</span><span class="calendar-event-meta">${e(scheduleWeightLabel(item))} · ${scheduleWeekLabel(item)}</span>`
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
  const visible = unique(selection.week === 'undated' ? unscheduled : weekData ? weekData.items : all).filter(inModule).sort((a,b) => (a.week ?? Infinity) - (b.week ?? Infinity) || a.module_title.localeCompare(b.module_title) || a.name.localeCompare(b.name));
  const empty = '<p class="agenda-empty">No assessments '+(selection.week ? 'in this week or selection.' : 'have been published for this selection.')+'</p>';
  const weekMap = `<section class="term-map" aria-label="Whole trimester" ${selection.layout === 'list' ? 'hidden' : ''}>
    <div class="term-caption"><div><h2>Teaching weeks</h2><p>Open an assessment to view its source. Ranges appear in each week they cover.</p></div><span class="term-length">${state.project.week_count} weeks</span></div>
    <div class="week-navigator">${weeks.map(week => {
      const items = unique(week.items.filter(inModule));
      const selected = selection.week === String(week.week);
      return `<section class="week-tile${items.length ? ' has-assessments' : ''}${selected ? ' is-selected' : ''}" aria-label="Week ${week.week} assessments">
        ${button(`<span class="week-heading">Week <strong>${week.week}</strong></span><span class="week-count">${items.length}</span>`, 'schedule-week', `data-week="${week.week}" aria-label="Week ${week.week}, ${items.length} assessments" aria-pressed="${selected}"`, 'calendar-week-button')}
        <div class="calendar-events">${items.map(item => sourceItem(item,true)).join('') || '<p class="week-empty">No assessments</p>'}</div>
      </section>`;
    }).join('')}</div>
    <div class="calendar-footer"><p>${filtered.length} unique assessments · ${undatedCount} undated</p><div>${undatedCount ? button(`Undated · ${undatedCount}`, 'schedule-week', 'data-week="undated" aria-label="Undated"', 'text-button') : ''}${selection.week ? button('Show all weeks', 'schedule-week', 'data-week=""', 'text-button') : ''}</div></div>
  </section>`;
  const undated = undatedCount ? `<section class="undated-assessments${selection.week === 'undated' ? ' is-selected' : ''}" tabindex="-1" aria-label="Undated assessments"><h2>Undated <span>${undatedCount}</span></h2><p>These assessments have no confirmed week.</p><div class="calendar-events">${unique(unscheduled.filter(inModule)).map(item => sourceItem(item,true)).join('')}</div></section>` : '';
  const activeModule = modules().find(module => module.id === selection.module)?.module_title || 'All modules';
  const activeWeek = selection.week === 'undated' ? 'Undated' : weekData ? `Week ${weekData.week}` : 'All weeks';
  const agenda = `<section class="assessment-agenda schedule-list" aria-label="Assessments by due week">
    <div class="list-toolbar"><div class="agenda-heading" tabindex="-1"><h2>Assessment list</h2><p>Ordered by first week · Multi-week assessments appear once.</p></div><div class="list-week-filter"><label for="list-week">Teaching week</label><select id="list-week" data-schedule-week><option value="">All weeks</option>${weeks.map(week => `<option value="${week.week}" ${String(week.week) === selection.week ? 'selected' : ''}>Week ${week.week}</option>`).join('')}<option value="undated" ${selection.week === 'undated' ? 'selected' : ''}>Undated</option></select></div></div>
    <div class="list-filter-summary"><p role="status">Showing <strong>${visible.length} of ${all.length}</strong> assessments <span>· ${e(activeModule)} · ${activeWeek}</span></p>${selection.week || selection.module ? button('Clear filters', 'schedule-clear', '', 'text-button') : ''}</div>
    ${visible.length ? `<table class="agenda-table"><caption class="sr-only">Assessments ordered by first teaching week. ${e(activeModule)}, ${activeWeek}.</caption><thead><tr><th scope="col">Assessment</th><th scope="col">Module</th><th scope="col">Teaching week</th><th scope="col">Weight</th></tr></thead><tbody>${visible.map(item => `<tr class="assessment-row" style="${moduleStyle(item.module_id)}"><td class="assessment-name">${sourceItem(item)}</td><td class="module-cell"><span class="module-label">${e(item.module_title)}</span></td><td class="due-label">${scheduleWeekLabel(item)}</td><td class="weight-label">${scheduleWeightLabel(item)}</td></tr>`).join('')}</tbody></table>` : empty}
  </section>`;
  return `<section class="schedule-workspace" aria-label="Assessment schedule"><div class="page-heading"><div><p class="eyebrow">${e(state.project.name)}</p><h1>Your assessment schedule</h1></div><div class="view-switch" role="group" aria-label="Schedule view">${button('Calendar', 'schedule-layout', `data-layout="timeline" aria-pressed="${selection.layout === 'timeline'}"`)}${button('List', 'schedule-layout', `data-layout="list" aria-pressed="${selection.layout === 'list'}"`)}</div></div>
    <div class="module-filters" role="group" aria-label="Filter modules">${button(`All modules<span class="filter-count">${all.length}</span>`, 'schedule-module', `data-module="" aria-label="All modules" aria-pressed="${!selection.module}"`)}${modules().map(module => button(`<span class="module-swatch" aria-hidden="true"></span><span class="filter-name">${e(module.module_title)}</span><span class="filter-count">${all.filter(item => item.module_id === module.id).length}</span>`, 'schedule-module', `style="${moduleStyle(module.id)}" data-module="${e(module.id)}" aria-label="${e(module.module_title)}" aria-pressed="${selection.module === module.id}"`)).join('')}${selection.layout === 'list' ? '' : `<span role="status">${filtered.length} assessment${filtered.length === 1 ? '' : 's'} in view</span>`}</div>
    ${weekMap}${selection.layout === 'list' ? agenda : undated}
  </section>`;
}

function terminalView() {
  const project = state.project;
  return `<section class="processing-issue terminal-failure" role="alert"><div class="issue-icon" aria-hidden="true">!</div><div class="issue-copy"><p class="issue-kicker">${e(project.name)} · ${e(project.status)}</p><h1>${project.status === 'Interrupted' ? 'Processing was interrupted' : 'We could not finish processing'}</h1><p>No usable assessments are available yet. Inspect the documents below, retry extraction, or replace an unclear source. Your uploaded documents are preserved.</p><ul>${(project.issues || []).map(issue => `<li><strong>${e(modules().find(m => m.id === issue.module_id)?.module_title || 'Trimester')}</strong><span>${e(issue.message)}${issue.document_id ? ` · Document ${e(issue.document_id)}` : ''}</span></li>`).join('')}</ul>${recoveryDocuments()}<div class="issue-actions">${button('Create new trimester', 'restart', '', 'primary')}</div></div></section>`;
}
const pendingReplacements = new Map();
function recoveryDocuments() {
  const project = state.project;
  const documents = [...(project?.documents || state.progress?.documents || [])].sort((a,b) => Number(Boolean(b.retryable)) - Number(Boolean(a.retryable)));
  const running = project.status === 'Processing';
  return `<section class="document-progress recovery-documents" aria-label="Document recovery"><h3>Source documents</h3><ul class="document-progress-list">${documents.map(doc => {
    const active = ['queued','running'].includes(doc.execution);
    const failed = doc.execution === 'failed' || ['failed','interrupted','not_processed'].includes(doc.state);
    const status = active ? (doc.execution === 'queued' ? 'Queued' : 'Processing') : failed ? 'Needs attention' : doc.inference === 'understood' ? 'Processed' : 'Review needed';
    const selected = pendingReplacements.get(doc.document_id);
    const issues = [...(doc.issues || []), ...(project.issues || []).filter(issue => issue.document_id === doc.document_id)];
    const messages = [...new Set(issues.map(issue => issue.message))];
    const locked = running ? 'data-disabled="true" disabled' : '';
    return `<li class="document-progress-item ${active ? 'is-active' : ''}" data-document-id="${e(doc.document_id)}" data-document-state="${e(doc.state)}"><div class="recovery-document-head"><span class="document-progress-name"><strong>${e(doc.filename)}</strong><small>${e(doc.module_title)}</small></span><span class="recovery-status ${failed ? 'needs-attention' : ''}" role="status">${active ? '<i class="recovery-spinner" aria-hidden="true"></i>' : ''}${status}</span></div>${messages.length ? `<p class="recovery-explanation">${e(messages.join(' '))}</p>` : failed ? '<p class="recovery-explanation">We couldn’t finish extracting this document. Retry the saved file or choose a replacement.</p>' : ''}${(doc.uncertainties || []).map(note => `<p class="recovery-explanation">${e(note)}</p>`).join('')}<div class="recovery-actions"><a href="${e(doc.original_url || `/api/documents/${doc.document_id}/original`)}" target="_blank" rel="noopener">View original ↗</a><a href="/documents?project=${e(project.id)}&document=${e(doc.document_id)}">Extracted text</a>${doc.retryable ? button('Retry document', 'retry-document', `data-document="${e(doc.document_id)}" data-generation="${doc.generation}" ${locked}`) : ''}${project.coverage !== 'complete' && (failed || doc.retryable || doc.inference !== 'understood') ? `<label class="replacement-label">Choose replacement<input type="file" accept=".pdf,.png,.jpg,.jpeg" data-replace-document="${e(doc.document_id)}" data-generation="${doc.generation}" aria-label="Replace ${e(doc.filename)}" ${locked}></label>` : ''}</div>${selected ? `<div class="replacement-review"><p>Replace <strong>${e(doc.filename)}</strong> with <strong>${e(selected.file.name)}</strong> (${Math.ceil(selected.file.size/1024)} KB)?</p><p>Existing assessments stay visible until the replacement is processed. They may be out of date.</p>${button('Upload replacement','confirm-replacement',`data-document="${e(doc.document_id)}" ${locked}`,'primary')}${button('Cancel','cancel-replacement',`data-document="${e(doc.document_id)}"`)}</div>` : ''}</li>`;
  }).join('')}</ul>${running ? '<p class="recovery-explanation">Processing continues. You can use the schedule while you wait. Other recovery actions become available when processing finishes.</p>' : ''}</section>`;
}
function sourceIssue() {
  const project = state.project;
  const issues = project?.issues || [];
  if (!issues.length && project?.coverage !== 'partial') return '';
  if (project.coverage !== 'partial') return `<section class="processing-issue source-issue" aria-label="Source availability"><div class="issue-copy"><h2>Some original documents are unavailable</h2><p>The schedule and saved source text remain available.</p><ul>${issues.map(issue => `<li>${e(issue.message)}</li>`).join('')}</ul></div></section>`;
  const unresolved = (project.documents || []).filter(doc => doc.execution !== 'succeeded' || doc.inference !== 'understood' || doc.issues?.length);
  return `<section class="coverage-notice" aria-label="Schedule coverage"><div class="coverage-heading"><span class="coverage-symbol" aria-hidden="true">!</span><div><p class="issue-kicker">${project.stale ? 'Previous results retained' : 'Partial schedule'}</p><h2>Some deadlines or assessment details may be missing</h2><p>${project.stale ? 'These results may be out of date while replacement or conflicting sources are resolved.' : 'Validated assessments are available below. Unresolved sources may add or change deadlines.'}</p></div><span class="coverage-count">${unresolved.length ? `${unresolved.length} source${unresolved.length === 1 ? '' : 's'} to resolve` : 'Review sources'}</span></div><details class="recovery-disclosure"><summary>Review documents &amp; recovery options</summary>${recoveryDocuments()}</details></section>`;
}
function feedbackView() {
  return `<div class="feedback-stack" aria-label="Errors and warnings">${state.error ? `<div class="message error" role="alert"><p>${e(state.error)}</p>${state.uncertain && state.project ? button('Check submission status', 'recover') : button('Reload saved results', 'reload')}</div>` : ''}</div>`;
}
function render() {
  const recoveryOpen = app.querySelector('.recovery-disclosure')?.open;
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
  app.innerHTML = `<main id="main" tabindex="-1">${state.step === 'schedule' ? feedbackView() + sourceIssue() + content : content + feedbackView()}</main>`;
  if (recoveryOpen) app.querySelector('.recovery-disclosure')?.setAttribute('open', '');
  showBusy();
  const selected = new URL(location.href).searchParams.get('assessment');
  if (selected) {
    const links = [...document.querySelectorAll('[data-document-preview]')].filter(a => a.getClientRects().length && new URL(a.href).searchParams.get('assessment') === selected);
    (links.find(a => a.closest('.week-tile.is-selected')) || links[0])?.focus({preventScroll:true});
  }
}
function showBusy() {
  document.body.classList.toggle('loading-page', Boolean(state.busy && (state.busy.screen || state.step === 'processing')));
  document.querySelector('.topbar').hidden = document.body.classList.contains('loading-page');
  app.querySelector('.input-workspace')?.toggleAttribute('hidden', Boolean(state.busy?.stage === 'uploading'));
  const existing = document.querySelector('[data-busy]');
  if (!state.busy) existing?.remove();
  if (state.busy) {
    if (!state.limits) app.querySelector('#main > [data-loading]:not([data-busy])')?.remove();
    const processingContext = app.querySelector('.processing-context');
    if (processingContext && !existing) processingContext.replaceChildren();
    const target = processingContext || app.querySelector('#main') || app;
    const markup = waiting(state.busy).replace('data-loading', 'data-loading data-busy');
    if (existing?.querySelector('.processing-panel') && (state.busy.screen || state.step === 'processing')) {
      const template = document.createElement('template'); template.innerHTML = markup;
      const next = template.content.firstElementChild;
      existing.className = next.className; existing.setAttribute('aria-label', next.getAttribute('aria-label'));
      const before = existing.querySelector('.processing-copy'), after = next.querySelector('.processing-copy');
      if (before.innerHTML !== after.innerHTML) before.innerHTML = after.innerHTML;
      const oldNote = existing.querySelector('.processing-footnote');
      const newNote = next.querySelector('.processing-footnote');
      if (oldNote && oldNote.innerHTML !== newNote.innerHTML) oldNote.innerHTML = newNote.innerHTML;
      const previousSteps = existing.querySelector('.checkpoint-list');
      const nextSteps = next.querySelector('.checkpoint-list');
      if (nextSteps && !previousSteps) existing.querySelector('.processing-panel').append(nextSteps);
      else if (previousSteps && nextSteps) {
        [...previousSteps.children].forEach((step, index) => {
          const updated = nextSteps.children[index];
          if (step.outerHTML === updated.outerHTML) return;
          step.className = updated.className;
          if (updated.hasAttribute('aria-current')) step.setAttribute('aria-current', 'step');
          else step.removeAttribute('aria-current');
          step.querySelector('.checkpoint-label').textContent = updated.querySelector('.checkpoint-label').textContent;
          step.querySelector('.checkpoint-state').textContent = updated.querySelector('.checkpoint-state').textContent;
        });
      }
    } else { existing?.remove(); target.insertAdjacentHTML('beforeend', markup); }
  }
  const context = app.querySelector('.processing-context');
  if (context && !state.busy && state.error) context.innerHTML = '<h1>Processing status unavailable</h1><p>Your submission may still be processing. Check its status below before submitting again.</p>' + documentProgressView(true);
  // Keep the live status outside a busy region so stage changes are announced.
  app.querySelector('.input-workspace')?.setAttribute('aria-busy', String(Boolean(state.busy)));
  app.querySelectorAll('button, input, select').forEach(el => { el.disabled = Boolean(state.busy) || (state.uncertain && el.dataset.action !== 'recover' && el.dataset.action !== 'restart') || el.dataset.disabled === 'true'; });
  document.querySelector('#project-picker').disabled = Boolean(state.busy);
  document.querySelector('#new-project').disabled = Boolean(state.busy);
  document.querySelectorAll('.workflow-steps button').forEach(el => {
    el.disabled = Boolean(state.busy) || (el.dataset.action === 'schedule' && !state.schedule);
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
  if (state.project?.id !== project.id) { state.progress = null; pendingReplacements.clear(); }
  for (const [id, selected] of pendingReplacements) {
    const current = project.documents?.find(doc => doc.document_id === id);
    if (project.documents && (!current || current.generation !== selected.generation)) pendingReplacements.delete(id);
  }
  state.project = project; state.schedule = project.schedule;
  if (project.documents) state.progress = { documents: project.documents, total_documents: project.documents.length, extracted_documents: project.documents.filter(d => d.state === 'extracted').length };
  state.step = project.status === 'Created' ? 'upload' : project.schedule ? 'schedule' : ['Failed', 'Interrupted', 'Partial', 'Ready'].includes(project.status) ? 'failure' : 'processing';
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
async function waitForJob(jobId, token) {
  const updates = new ProcessingEvents(state.project.id);
  try {
    while (true) {
      await waitForVisiblePage(); assertCurrent(token);
      const job = await request(`/api/jobs/${jobId}`); assertCurrent(token);
      const progressChanged = JSON.stringify(state.progress) !== JSON.stringify(job.progress || null);
      state.progress = job.progress || null;
      if (!['queued', 'running'].includes(job.status)) return job;
      if (state.schedule || progressChanged && state.progress?.extracted_documents) {
        const snapshot = await request(`/api/projects/${state.project.id}`); assertCurrent(token);
        if (snapshot.schedule && (state.busy || JSON.stringify(snapshot) !== JSON.stringify(state.project))) {
          selectProject(snapshot); state.busy = null; render();
        }
      }
      const detail = processingFeedback(job.stage, state.progress?.documents || []);
      if (state.busy && (state.busy.detail !== detail || state.busy.stage !== job.stage || progressChanged)) {
        state.busy.detail = detail; state.busy.stage = job.stage; showBusy();
      }
      await updates.wait(JOB_POLL_INTERVAL_MS);
    }
  } finally { updates.close(); }
}
async function confirmCompletion(token) {
  state.busy = { label: 'Your schedule is ready.', stage: 'complete', screen: true };
  showBusy();
  await new Promise(resolve => setTimeout(resolve, 1000));
  assertCurrent(token);
}
async function refreshProject(id) {
  const token = operation;
  const wasProcessing = state.step === 'processing';
  const project = await request(`/api/projects/${id}`); assertCurrent(token);
  if (wasProcessing && project.status === 'Ready') await confirmCompletion(token);
  selectProject(project);
  if (state.project.status === 'Processing') {
    state.busy = state.schedule ? null : { label: 'Processing your documents…', detail: 'Your submission is saved. Checking processing status…' };
    render(); await waitForJob(state.project.job_id, token);
    const terminal = await request(`/api/projects/${id}`); assertCurrent(token);
    if (terminal.status === 'Ready' && !state.schedule) await confirmCompletion(token);
    selectProject(terminal);
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
  const limits = await request('/api/limits'); assertCurrent(token); configureInputLimits(limits); state.limits = limits;
  const projects = await request('/api/projects'); assertCurrent(token); state.projects = projects;
  const id = new URL(location.href).searchParams.get('project');
  if (id) await refreshProject(id); else { state.project = null; state.schedule = null; state.progress = null; state.step = 'upload'; }
}
function startNew() {
  operation++;
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
  }, { screen: true, stage: 'uploading', detail: 'Uploading and checking acceptance. Keep this tab open.' });
}
const recoveryKeys = new Map();
async function retryDocument(target) {
  if (state.project.status === 'Processing') return;
  const projectId = state.project.id;
  const id = target.dataset.document;
  const generation = Number(target.dataset.generation);
  const identity = `${id}:${generation}`;
  if (!recoveryKeys.has(identity)) recoveryKeys.set(identity, crypto.randomUUID());
  await run('Retrying this document…', async () => {
    const token = operation;
    await request(`/api/documents/${id}/retry`, {method: 'POST', headers: {'Idempotency-Key': recoveryKeys.get(identity)}, body: {expected_generation: generation}});
    assertCurrent(token); await refreshProject(projectId);
  });
}
function replaceDocument(input) {
  const file = input.files[0]; if (!file) return;
  const id = input.dataset.replaceDocument;
  if (!/\.(pdf|png|jpe?g)$/i.test(file.name) || file.type && !state.limits.media_types.includes(file.type) || !file.size || file.size > Math.min(state.limits.document_bytes, state.limits.request_bytes)) {
    state.error = `Choose a non-empty PDF, PNG or JPG up to ${Math.min(state.limits.document_bytes, state.limits.request_bytes)/1048576} MB.`;
    render(); return;
  }
  pendingReplacements.set(id, { file, generation: Number(input.dataset.generation), key: crypto.randomUUID() });
  state.error = ''; render();
  [...app.querySelectorAll('[data-action="confirm-replacement"]')].find(el => el.dataset.document === id)?.focus({preventScroll:true});
}
async function confirmReplacement(target) {
  const id = target.dataset.document, selected = pendingReplacements.get(id);
  if (!selected || state.project.status === 'Processing') return;
  const projectId = state.project.id;
  await run('Uploading replacement…', async () => {
    const token = operation;
    await request(`/api/documents/${id}/replacement`, {method:'POST', headers:{'Idempotency-Key':selected.key, 'Expected-Generation':String(selected.generation), 'X-Filename':encodeURIComponent(selected.file.name), 'Content-Type':selected.file.type || 'application/octet-stream'}, body:selected.file});
    assertCurrent(token); pendingReplacements.delete(id);
    await refreshProject(projectId);
  });
}
document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]'); if (!target || state.busy) return;
  const action = target.dataset.action;
  if (action === 'schedule-clear') {
    const url = new URL(location.href);
    for (const key of ['week','module','assessment']) url.searchParams.delete(key);
    history.replaceState(null,'',url); render();
    app.querySelector('.agenda-heading')?.focus({preventScroll:true});
    return;
  }
  if (['schedule-layout','schedule-week','schedule-module'].includes(action)) {
    const key = action.replace('schedule-', '');
    const value = target.dataset[key];
    const url = new URL(location.href); value ? url.searchParams.set(key,value) : url.searchParams.delete(key);
    url.searchParams.delete('assessment'); history.replaceState(null,'',url); render();
    [...document.querySelectorAll(`[data-action="${action}"]`)].find(el => el.dataset[key] === value)?.focus({preventScroll:true});
    if (action === 'schedule-week' && value) {
      const heading = app.querySelector(scheduleParams().layout === 'list' ? '.agenda-heading' : value === 'undated' ? '.undated-assessments' : '.week-tile.is-selected .calendar-week-button');
      heading?.focus({preventScroll:true});
      heading?.scrollIntoView({block:'nearest'});
    }
    return;
  }
  if (action === 'restart' || action === 'upload') { startNew(); return; }
  if (state.step === 'upload' && handleInputAction(target, render)) return;
  if (action === 'confirm-replacement') await confirmReplacement(target);
  if (action === 'cancel-replacement') { pendingReplacements.delete(target.dataset.document); render(); }
  if (action === 'retry-document') await retryDocument(target);
  if (action === 'build-schedule') await buildSchedule();
  if (action === 'recover') await run('Checking submission status…', async () => { await refreshProject(state.project.id); if (state.project.status === 'Created') { state.uncertain = true; state.error = 'No acceptance is recorded yet. Keep checking status, or start a new trimester. This submission will not be resent.'; } });
  if (action === 'reload') await run('Loading saved results…', loadSaved);
  if (action === 'schedule' && state.schedule) { state.step = 'schedule'; syncUrl(true); render(); }
});
document.querySelector('#project-picker').onchange = async event => {
  if (!event.target.value) return;
  await run('Loading assessments…', async () => { await refreshProject(event.target.value); syncUrl(true); });
};
document.addEventListener('input', event => { if (state.step === 'upload' && !state.busy) handleInputChange(event); });
document.addEventListener('change', event => {
  if (event.target.matches('[data-schedule-week]')) {
    const url = new URL(location.href);
    event.target.value ? url.searchParams.set('week',event.target.value) : url.searchParams.delete('week');
    url.searchParams.delete('assessment'); history.replaceState(null,'',url); render();
    app.querySelector('[data-schedule-week]')?.focus({preventScroll:true});
    return;
  }
  if (event.target.matches('[data-replace-document]') && !state.busy) replaceDocument(event.target);
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
