import { request } from './api.js';
import { bucket, inputView, resetInput, handleInputAction, handleInputChange, addInputFiles, saveInputModule, showInputError } from './input-workspace.js';
import { weeks, escape as e, assessments, datedPlanItems, weekLabel, weightLabel, capacity, newestPlan } from './model.js';

const app = document.querySelector('#app');
const state = { step: 'upload', projects: [], project: null, schedule: null, busy: null, error: '', warnings: [], plan: null, moduleTab: 0 };
const base = () => `/api/projects/${state.project.id}`;
const button = (label, action, extra = '', cls = '') => `<button type="button" data-action="${action}" class="${cls}" ${extra}>${label}</button>`;
const modules = () => state.project?.modules || [];
const isRecess = week => state.schedule?.recess_weeks?.includes(week);
const activeModule = () => modules()[state.moduleTab] || modules()[0];
function waiting({ label, screen = false, detail = '' }) {
  const message = detail || 'Waiting for the API response. You can keep this page open.';
  const loader = '<div class="loader-stack" aria-hidden="true"><i></i><i></i><i></i></div>';
  const progress = '<div class="loading-track" aria-hidden="true"><span></span></div>';
  if (screen) {
    return `<section class="processing-screen" data-loading role="status" aria-live="polite" aria-label="${e(label)}"><div class="processing-panel">${loader}<div><p class="eyebrow">Stackplan is working</p><h1>${e(label)}</h1><p>${e(message)}</p></div>${progress}</div></section>`;
  }
  return `<section class="request-status" data-loading role="status" aria-live="polite" aria-label="${e(label)}">${loader}<div><strong>${e(label)}</strong><p>${e(message)}</p></div>${progress}</section>`;
}
function render() {
  document.body.classList.toggle('input-page', state.step === 'upload');
  const select = document.querySelector('#project-picker');
  select.innerHTML = `<option value="">Open a saved trimester</option>${state.projects.map(p => `<option value="${p.id}" ${p.id === state.project?.id ? 'selected' : ''}>${e(p.name)}</option>`).join('')}`;
  select.disabled = Boolean(state.busy);
  document.querySelector('#new-project').disabled = Boolean(state.busy);
  document.querySelectorAll('[data-step]').forEach(el => {
    if (el.dataset.step === state.step) el.setAttribute('aria-current', 'step'); else el.removeAttribute('aria-current');
  });
  app.innerHTML = `<main id="main" tabindex="-1">${state.error ? `<div class="message error" role="alert"><p>${e(state.error)}</p>${button('Reload saved results', 'reload')}</div>` : ''}${state.warnings.length ? `<div class="message" role="status"><div>${state.warnings.map(w => `<p>${e(w)}</p>`).join('')}</div></div>` : ''}${({ upload: uploadView, schedule: scheduleView, plan: planView })[state.step]()}</main>`;
  showBusy();
}
function showBusy() {
  document.querySelector('[data-loading]')?.remove();
  if (state.busy) app.insertAdjacentHTML('beforeend', waiting(state.busy));
  app.setAttribute('aria-busy', String(Boolean(state.busy)));
  app.querySelectorAll('button, input, select').forEach(el => { el.disabled = Boolean(state.busy) || el.dataset.disabled === 'true'; });
  document.querySelector('#project-picker').disabled = Boolean(state.busy);
  document.querySelector('#new-project').disabled = Boolean(state.busy);
}
function uploadView() { return inputView(state.project); }
function timeline() {
  return `<div class="timeline-scroll" role="region" aria-label="Week 1 to 14 assessment schedule" tabindex="0"><div class="timeline"><div class="lane-label timeline-heading">MODULE / WEEK</div>${weeks.map(w => `<div class="week-heading ${isRecess(w) ? 'recess' : ''}"><span>${isRecess(w) ? 'RECESS' : 'WEEK'}</span><strong>${w}</strong></div>`).join('')}${modules().map((m, moduleIndex) => `<div class="lane-label"><strong>${e(m.module_title)}</strong><small>${m.credit} credits</small></div>${weeks.map(w => `<div class="week-cell ${isRecess(w) ? 'recess' : ''}">${(state.schedule?.weeks.find(v => v.week === w)?.items || []).filter(i => i.module_title === m.module_title).map(i => `<a class="milestone" href="#assessment-${encodeURIComponent(i.assessment_id)}" data-action="open-assessment" data-module-index="${moduleIndex}" data-assessment-id="${encodeURIComponent(i.assessment_id)}">${e(i.name)}</a>`).join('')}</div>`).join('')}`).join('')}</div></div>`;
}
function scheduleView() {
  const unresolved = state.schedule?.unscheduled || [];
  return `<div class="page-heading"><div><p class="eyebrow">${e(state.project.name)}</p><h1>Your <em>assessments.</em></h1></div>${button('View study plan ↗', 'plan', '', 'primary')}</div><section class="paper fact-panel">${timeline()}${unresolved.length ? `<p class="warning">${unresolved.length} assessment(s) have no confirmed week. They are listed below.</p>` : ''}</section>${moduleBrowser()}`;
}
function moduleBrowser() {
  const selected = activeModule();
  if (!selected) return '';
  return `<section class="module-browser" aria-labelledby="module-browser-title"><div class="section-heading"><div><p class="eyebrow">Assessment details</p><h2 id="module-browser-title">Browse by module</h2></div><p>Open one module at a time.</p></div><div class="module-tabs" role="tablist" aria-label="Module assessment details">${modules().map((module, index) => `<button type="button" class="module-tab" role="tab" id="module-tab-${index}" aria-controls="module-panel-${index}" aria-selected="${index === state.moduleTab}" tabindex="${index === state.moduleTab ? 0 : -1}" data-action="module-tab" data-module-index="${index}">${e(module.module_title)}<span>${assessments(module).length}</span></button>`).join('')}</div><section class="assessment-module paper" role="tabpanel" tabindex="0" id="module-panel-${state.moduleTab}" aria-labelledby="module-tab-${state.moduleTab}"><h2>${e(selected.module_title)} <small>${selected.credit} credits</small></h2><div class="table-scroll"><table><caption class="sr-only">${e(selected.module_title)} assessment details</caption><thead><tr><th>Assessment</th><th>Week</th><th>Weight</th></tr></thead><tbody>${assessments(selected).map(a => `<tr id="assessment-${encodeURIComponent(a.assessment_id)}"><td><strong>${e(a.name)}</strong><small>${e(a.group.type)}${a.record_role === 'group' ? ' · group total, not a separate event' : ''}</small></td><td>${e(weekLabel(a.schedule))}</td><td>${e(weightLabel(a))}</td></tr>`).join('')}</tbody></table></div></section></section>`;
}
function studyPlanIssue() {
  const prefixes = [
    'AI Manager error: recommendation:',
    'Logic Manager error: Invalid AI recommendation:',
  ];
  for (const run of state.project?.pipeline_runs || []) {
    const issue = (run.errors || []).find(error => prefixes.some(prefix => error.startsWith(prefix)));
    const prefix = prefixes.find(value => issue?.startsWith(value));
    if (issue && prefix) return issue.replace(prefix, '').trim();
  }
  return '';
}
function unknownSection() {
  const unknown = state.schedule?.unscheduled || [];
  if (!unknown.length) return '';
  const moduleCounts = unknown.reduce((groups, item) => ({ ...groups, [item.module_title]: (groups[item.module_title] || 0) + 1 }), {});
  const uniqueItems = [...unknown.reduce((items, item) => {
    const groupedName = item.name.replace(/\s+(?:#?\d+|[IVX]+)$/i, '').trim() || item.name;
    const key = `${item.module_title}\u0000${item.assessment_type}\u0000${groupedName}`;
    const existing = items.get(key);
    items.set(key, existing ? { ...existing, count: existing.count + 1 } : { ...item, name: groupedName, count: 1 });
    return items;
  }, new Map()).values()];
  return `<section class="paper unknown-panel compact-unknown"><div class="unknown-summary"><div><p class="eyebrow">Worth checking</p><h2>Dates to confirm</h2><p>${unknown.length} assessment${unknown.length === 1 ? '' : 's'} kept out of the numbered plan.</p></div><div class="unknown-counts">${Object.entries(moduleCounts).map(([module, count]) => `<span><strong>${e(module)}</strong>${count}</span>`).join('')}</div></div><details><summary>See affected assessments</summary><ul>${uniqueItems.map(item => `<li>${e(item.module_title)} · ${e(item.name)}${item.count > 1 ? ` ×${item.count}` : ''}</li>`).join('')}</ul></details></section>`;
}
function planView() {
  const record = state.plan;
  return `<div class="page-heading"><div><p class="eyebrow">Study plan</p><h1>Your <em>study plan.</em></h1></div>${button('← Assessments', 'schedule')}</div>${record ? planResult(record) : `<div class="message error" role="alert"><p>Your assessment schedule is safe, but the study plan was not generated.</p>${studyPlanIssue() ? `<p>Reason: ${e(studyPlanIssue())}</p>` : '<p>Reprocess the screenshots to try again.</p>'}</div><section class="paper fact-panel"><h2>Assessment timetable</h2>${timeline()}</section>`}${unknownSection()}`;
}
function planSuggestions(record) {
  const defaults = ['Start here', 'Plan ahead', 'Keep in mind'];
  const highlights = Array.isArray(record.recommendation_payload.highlights)
    ? record.recommendation_payload.highlights.slice(0, 3)
    : [];
  const suggestions = highlights.map((highlight, index) => {
    if (typeof highlight === 'string') {
      return { title: defaults[index], suggestion: highlight };
    }
    return {
      title: highlight?.title || defaults[index],
      suggestion: highlight?.suggestion || '',
    };
  }).filter(item => item.suggestion.trim());
  if (suggestions.length) return suggestions;
  const summary = record.recommendation_payload.summary;
  return typeof summary === 'string' && summary.trim()
    ? [{ title: 'Start here', suggestion: summary }]
    : [];
}
function planResult(record) {
  const items = datedPlanItems(record, state.schedule?.unscheduled);
  const totals = capacity(items, record.preferences.available_hours_per_week);
  const activeWeeks = totals.filter(week => week.hours > 0);
  const plannedHours = Math.round(items.reduce((sum, item) => sum + item.estimated_hours, 0) * 100) / 100;
  const firstUpcomingWeek = activeWeeks[0]?.week;
  const suggestions = planSuggestions(record);
  const weeklyPlan = activeWeeks.map(week => {
    const weekItems = items.filter(item => item.week === week.week);
    const focus = record.recommendation_payload.weeks?.find(value => value.week === week.week)?.focus || 'Planned actions';
    return `<details class="week-plan" ${week.week === firstUpcomingWeek ? 'open' : ''}><summary><span><small>Week ${week.week}</small><strong>${e(focus)}</strong></span><span>${week.hours}h · ${weekItems.length} action${weekItems.length === 1 ? '' : 's'}</span></summary><ul class="tasks compact-tasks">${weekItems.map(item => `<li><div class="task-title"><h3>${e(item.title)}</h3><span class="priority priority-${e(item.priority)}">${e(item.priority)}</span></div><p class="task-context"><strong>${e(item.module_title || 'All modules')}</strong><span>${item.estimated_hours}h</span></p></li>`).join('')}</ul></details>`;
  }).join('');
  return `<section class="plan-suggestions"><div class="section-heading"><div><p class="eyebrow">Suggested focus</p><h2>Suggestions</h2></div></div><div class="suggestion-grid">${suggestions.map(item => `<article class="suggestion-card"><h3>${e(item.title)}</h3><p>${e(item.suggestion)}</p></article>`).join('')}</div></section><div class="stats plan-stats"><div><span>Active weeks</span><strong>${activeWeeks.length}</strong><small>with useful actions</small></div><div><span>Planned time</span><strong>${plannedHours}h</strong><small>across the trimester</small></div><div><span>Actions</span><strong>${items.length}</strong><small>from confirmed timing</small></div></div><section class="weekly-plan"><div class="section-heading"><div><p class="eyebrow">Plan by week</p><h2>Open only what you need</h2></div><p>Unknown dates stay outside this plan.</p></div>${weeklyPlan || '<p>No dated study actions were returned.</p>'}</section>`;
}
function syncUrl() {
  const url = new URL(location.href);
  if (state.project) { url.searchParams.set('project', state.project.id); url.searchParams.set('view', state.step); }
  else { url.searchParams.delete('project'); url.searchParams.delete('view'); }
  history.replaceState(null, '', url);
}
async function refreshProject(id) {
  const project = (await request(`/api/projects/${id}`)).payload;
  state.project = project;
  state.plan = newestPlan(project.recommendations);
  state.schedule = project.schedule || null;
  if (!modules()[state.moduleTab]) state.moduleTab = 0;
}
async function run(label, action, options = {}) {
  if (state.busy) return;
  state.busy = { label, ...options }; state.error = ''; state.warnings = []; showBusy();
  try { await action(); syncUrl(); render(); }
  catch (error) {
    state.error = error.message;
    // Keep the form and selected files intact so a failed request can be retried.
    let alert = document.querySelector('.message.error');
    if (!alert) { document.querySelector('#main').insertAdjacentHTML('afterbegin', '<div class="message error" role="alert"></div>'); alert = document.querySelector('.message.error'); }
    alert.innerHTML = `<p>${e(state.error)}</p>${button('Reload saved results', 'reload')}`;
  } finally { state.busy = null; showBusy(); }
}
async function loadSaved() {
  state.projects = (await request('/api/projects')).payload;
  const params = new URLSearchParams(location.search);
  const id = state.project?.id || Number(params.get('project'));
  if (id) { await refreshProject(id); state.step = modules().length ? params.get('view') === 'plan' ? 'plan' : 'schedule' : 'upload'; }
}
document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]'); if (!target || state.busy) return;
  const action = target.dataset.action;
  if (action === 'restart') { state.project = null; state.schedule = null; state.step = 'upload'; state.plan = null; state.moduleTab = 0; syncUrl(); state.error = ''; state.warnings = []; resetInput(); render(); }
  if (handleInputAction(target, render)) return;
  if (action === 'build-schedule') { await buildSchedule(); return; }
  if (action === 'module-tab') {
    state.moduleTab = Number(target.dataset.moduleIndex);
    render();
    document.querySelector(`#module-tab-${state.moduleTab}`)?.focus();
  }
  if (action === 'open-assessment') {
    event.preventDefault();
    state.moduleTab = Number(target.dataset.moduleIndex);
    render();
    document.getElementById(`assessment-${target.dataset.assessmentId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  if (action === 'plan' || action === 'schedule') { state.step = action; syncUrl(); render(); document.querySelector('#main').focus(); }
  if (action === 'reload') await run('Loading saved results…', loadSaved);
});
document.addEventListener('keydown', event => {
  const tab = event.target.closest('[role="tab"][data-module-index]');
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const lastIndex = modules().length - 1;
  if (event.key === 'Home') state.moduleTab = 0;
  if (event.key === 'End') state.moduleTab = lastIndex;
  if (event.key === 'ArrowLeft') state.moduleTab = state.moduleTab > 0 ? state.moduleTab - 1 : lastIndex;
  if (event.key === 'ArrowRight') state.moduleTab = state.moduleTab < lastIndex ? state.moduleTab + 1 : 0;
  render();
  document.querySelector(`#module-tab-${state.moduleTab}`)?.focus();
});
document.querySelector('#project-picker').addEventListener('change', async event => {
  if (!event.target.value) return;
  const id = Number(event.target.value);
  await run('Loading assessments…', async () => { await refreshProject(id); resetInput(); state.step = modules().length ? 'schedule' : 'upload'; });
});
document.addEventListener('input', event => {
  if (!state.busy && state.step === 'upload') handleInputChange(event);
});
document.addEventListener('change', event => {
  if (event.target.id !== 'module-images' || state.busy) return;
  addInputFiles(event.target.files);
  event.target.value = '';
});
for (const type of ['dragenter', 'dragover', 'dragleave', 'drop']) {
  document.addEventListener(type, event => {
    const drop = event.target.closest('#screenshot-drop');
    if (!drop) return;
    event.preventDefault();
    if (state.busy) return;
    if (type === 'dragenter' || type === 'dragover') drop.classList.add('is-dragging');
    if (type === 'dragleave' && !drop.contains(event.relatedTarget)) drop.classList.remove('is-dragging');
    if (type === 'drop') { drop.classList.remove('is-dragging'); addInputFiles(event.dataTransfer.files); }
  });
}
document.addEventListener('submit', event => {
  event.preventDefault();
  if (!state.busy && event.target.id === 'module-form') saveInputModule(render);
});
// Drafts contain local File objects, so make leaving with unsent work explicit.
window.addEventListener('beforeunload', event => {
  if (state.step === 'upload' && (bucket.entries.length || bucket.hasDraft)) {
    event.preventDefault();
    event.returnValue = '';
  }
});
async function buildSchedule() {
  const nameField = document.querySelector('#trimester-name');
  if (!nameField.reportValidity()) return;
  let submission;
  try { submission = bucket.submission(); }
  catch (error) { showInputError(error.message); return; }
  await run('Building your trimester…', async () => {
    if (!state.project) {
      state.project = (await request('/api/projects', { method: 'POST', body: { name: submission.name, week_count: 14 } })).payload;
      syncUrl();
      // A retry uses this same project and the same bucket of selected files.
      nameField.value = state.project.name;
      nameField.readOnly = true;
    }
    const result = await request(`${base()}/process`, { method: 'POST', body: submission.upload });
    state.warnings = result.errors || [];
    await refreshProject(state.project.id);
    state.projects = (await request('/api/projects')).payload;
    state.step = modules().length ? 'schedule' : 'upload';
    if (!modules().length && !state.warnings.length) state.warnings = ['No assessments were returned. Check your screenshots and try again.'];
  }, {
    screen: true,
    detail: 'Reading the module screenshots, building the Week 1–14 schedule, and generating your study plan. This may take a few minutes.',
  });
}

render();
run('Opening your workspace…', loadSaved, {
  screen: true,
  detail: 'Loading your saved trimesters and checking that the API is ready.',
});
