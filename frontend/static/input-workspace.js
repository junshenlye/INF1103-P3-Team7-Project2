import { escape as e } from './html.js';

const freshModule = () => ({ title: '', credit: '6', files: [] });
let inputLimits;
export function configureInputLimits(value) {
  const numericFields = ['module_count', 'documents_per_module', 'document_bytes', 'request_bytes', 'project_name_length', 'module_title_length', 'credit', 'week_count'];
  if (!value || numericFields.some(key => !Number.isSafeInteger(value[key]) || value[key] < 1) ||
      !Array.isArray(value.media_types) || !value.media_types.length || value.media_types.some(type => typeof type !== 'string' || !type.trim())) {
    throw new Error('Upload settings could not be loaded. Reload the page or check that the app is running the latest version.');
  }
  inputLimits = { ...value, media_types: [...value.media_types] };
}
const sizeLabel = bytes => `${bytes / (1024 * 1024)} MB`;
const icons = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  upload: '<path d="M12 16V4m-4 4 4-4 4 4M4 15v5h16v-5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  edit: '<path d="m14 5 5 5M4 20l5-1L20 8a2 2 0 0 0-5-5L4 14z"/>',
  file: '<path d="M14 3H5v18h14V8zM14 3v6h5M8 14h8M8 17h5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
const fileKey = file => `${file.name}:${file.size}:${file.lastModified}`;

// Files stay attached to their module when the editor is collapsed or reopened.
export class ModuleBucket {
  constructor() { this.reset(); }
  reset() {
    this.name = '';
    this.weekCount = '14';
    this.entries = [];
    this.draft = freshModule();
    this.editing = null;
    this.editor = null;
    this.removed = null;
    this.nextId = 1;
  }
  get current() { return this.editor || this.draft; }
  get hasDraft() { return Boolean(this.draft.title.trim() || this.draft.files.length || this.draft.credit !== '6'); }
  get canBuild() { return this.entries.length > 0 && this.editing === null && !this.hasDraft; }
  get totalSize() { return this.entries.reduce((sum, item) => sum + item.files.reduce((bytes, file) => bytes + file.size, 0), 0); }
  get hasChanges() {
    if (this.editing === null) return this.hasDraft;
    const original = this.entries.find(item => item.id === this.editing);
    return this.current.title !== original.title || this.current.credit !== original.credit ||
      this.current.files.length !== original.files.length || this.current.files.some((file, index) => file !== original.files[index]);
  }
  edit(id) {
    if (this.editing === id) return;
    if (this.editing !== null && this.hasChanges) throw new Error('Save or cancel your current changes before opening another module.');
    const item = this.entries.find(entry => entry.id === id);
    if (!item) return;
    this.editing = id;
    this.editor = { ...item, files: [...item.files] };
  }
  cancel() { this.editing = null; this.editor = null; }
  addFiles(files) {
    const incoming = [...files];
    if (incoming.some(file => !/\.(pdf|png|jpe?g)$/i.test(file.name) || (file.type && !inputLimits.media_types.includes(file.type)))) {
      throw new Error('Choose PDF, PNG or JPG documents.');
    }
    if (incoming.some(file => file.size > inputLimits.document_bytes || file.size === 0)) {
      throw new Error(`Each document must be non-empty and of ${sizeLabel(inputLimits.document_bytes)} or less.`);
    }
    const unique = new Map(this.current.files.map(file => [fileKey(file), file]));
    incoming.forEach(file => unique.set(fileKey(file), file));
    const filesAfter = [...unique.values()];
    const otherSize = this.entries.filter(item => item.id !== this.editing).reduce((sum, item) => sum + item.files.reduce((bytes, file) => bytes + file.size, 0), 0);
    const pendingSize = this.editing === null ? 0 : this.draft.files.reduce((sum, file) => sum + file.size, 0);
    if (otherSize + pendingSize + filesAfter.reduce((sum, file) => sum + file.size, 0) > inputLimits.request_bytes) {
      throw new Error(`Your complete upload must fit within ${sizeLabel(inputLimits.request_bytes)}.`);
    }
    if (filesAfter.length > inputLimits.documents_per_module) throw new Error(`Choose up to ${inputLimits.documents_per_module} documents per module.`);
    this.current.files = filesAfter;
  }
  save() {
    if (this.editing === null && this.entries.length >= inputLimits.module_count) throw new Error(`Submit up to ${inputLimits.module_count} modules.`);
    const item = this.current;
    const title = item.title.trim();
    if (!title) throw new Error('Give this module a title before adding it to your bucket.');
    if (title.length > inputLimits.module_title_length) throw new Error(`Keep the module title within ${inputLimits.module_title_length} characters.`);
    if (!Number.isInteger(Number(item.credit)) || Number(item.credit) < 1 || Number(item.credit) > inputLimits.credit) throw new Error('Enter credits within the displayed limits.');
    if (!item.files.length) throw new Error('Add at least one assessment document for this module.');
    if (this.entries.some(entry => entry.id !== this.editing && entry.title.toLowerCase() === title.toLowerCase())) {
      throw new Error('This module is already in your bucket. Use a different title or edit the existing module.');
    }
    const combinedSize = this.entries.filter(entry => entry.id !== this.editing).reduce((sum, entry) => sum + entry.files.reduce((bytes, file) => bytes + file.size, 0), 0) + item.files.reduce((sum, file) => sum + file.size, 0);
    if (combinedSize > inputLimits.request_bytes) throw new Error(`Keep the complete upload within ${sizeLabel(inputLimits.request_bytes)}.`);
    const saved = { ...item, title, files: [...item.files], id: this.editing ?? this.nextId++ };
    if (this.editing !== null) {
      this.entries[this.entries.findIndex(entry => entry.id === this.editing)] = saved;
      this.cancel();
    } else {
      this.entries.push(saved);
      this.draft = freshModule();
    }
    return saved;
  }
  remove() {
    const index = this.entries.findIndex(item => item.id === this.editing);
    if (index < 0) return;
    this.removed = { item: this.entries[index], index };
    this.entries.splice(index, 1);
    this.cancel();
  }
  undo() {
    if (!this.removed) return;
    if (this.entries.length >= inputLimits.module_count) throw new Error('Remove a module before restoring this one.');
    if (this.entries.some(item => item.title.toLowerCase() === this.removed.item.title.toLowerCase())) {
      throw new Error('A module now uses this title. Rename it before restoring the removed module.');
    }
    if (this.totalSize + this.removed.item.files.reduce((sum, file) => sum + file.size, 0) + this.draft.files.reduce((sum, file) => sum + file.size, 0) + (this.editor ? this.editor.files.reduce((sum, file) => sum + file.size, 0) - this.entries.find(item => item.id === this.editing).files.reduce((sum, file) => sum + file.size, 0) : 0) > inputLimits.request_bytes) {
      throw new Error(`Restoring this module would exceed ${sizeLabel(inputLimits.request_bytes)}. Remove some documents first.`);
    }
    this.entries.splice(this.removed.index, 0, this.removed.item);
    this.removed = null;
  }
  submission() {
    if (!this.canBuild) throw new Error('Add your current module to the bucket, or cancel its changes, before continuing.');
    if (this.totalSize > inputLimits.request_bytes) throw new Error(`Keep the complete upload within ${sizeLabel(inputLimits.request_bytes)}.`);
    if (!this.name.trim()) throw new Error('Name your trimester before continuing.');
    if (this.name.trim().length > inputLimits.project_name_length) throw new Error('Keep the trimester name within the displayed limit.');
    if (!Number.isInteger(Number(this.weekCount)) || Number(this.weekCount) < 1 || Number(this.weekCount) > inputLimits.week_count) throw new Error('Enter a week count within the displayed limits.');
    const upload = new FormData();
    const metadata = this.entries.map((item, index) => ({
      module_title: item.title,
      credit: Number(item.credit),
      file_fields: item.files.map((file, fileIndex) => {
        const field = `module_${index}_file_${fileIndex}`;
        upload.append(field, file);
        return field;
      }),
    }));
    upload.append('modules', JSON.stringify(metadata));
    return { name: this.name.trim(), upload };
  }
}

export const bucket = new ModuleBucket();
const previews = new Map();
let notice = '';
let reviewing = false;
let inputError = '';
function cleanPreviews() {
  const kept = new Set([...bucket.entries.flatMap(item => item.files), ...bucket.draft.files, ...(bucket.editor?.files || []), ...(bucket.removed?.item.files || [])]);
  for (const [file, url] of previews) if (!kept.has(file)) { URL.revokeObjectURL(url); previews.delete(file); }
}
export function resetInput() { reviewing = false; bucket.reset(); notice = ''; inputError = ''; cleanPreviews(); }

function fileList() {
  return bucket.current.files.map((file, index) => {
    if (!previews.has(file)) previews.set(file, URL.createObjectURL(file));
    return `<li>${file.type === 'application/pdf' || /\.pdf$/i.test(file.name) ? '<span aria-label="PDF document">PDF</span>' : `<img src="${previews.get(file)}" alt="">`}<span><strong>${e(file.name)}</strong><small>${file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`}</small></span><button type="button" class="icon-button" data-action="input-remove-file" data-index="${index}" aria-label="Remove ${e(file.name)}">${icon('close')}</button></li>`;
  }).join('');
}
function bucketCards() {
  if (!bucket.entries.length) return `<div class="bucket-empty"><span class="empty-stack" aria-hidden="true">${icon('file')}</span><strong>Your trimester starts here</strong><p>Added modules will appear here, ready for one final check.</p><div class="empty-module" aria-hidden="true"><i></i><span></span></div><div class="empty-module" aria-hidden="true"><i></i><span></span></div></div>`;
  return `<ol class="bucket-list">${bucket.entries.map((item, index) => `<li class="bucket-card ${bucket.editing === item.id ? 'is-editing' : ''}"><button type="button" class="bucket-open" data-action="input-edit" data-id="${item.id}" aria-label="Edit ${e(item.title)}" ${bucket.editing === item.id ? 'aria-current="true"' : ''}><span class="module-number">${String(index + 1).padStart(2, '0')}</span><span class="bucket-card-copy"><strong>${e(item.title)}</strong><small>${item.credit} credits <span>·</span> ${plural(item.files.length, 'source file')}</small></span><span class="bucket-edit">${icon('edit')}<span>${bucket.editing === item.id ? 'Editing' : 'Edit'}</span></span></button></li>`).join('')}</ol>`;
}
function buildHint() {
  if (reviewing) return `${plural(bucket.entries.length, 'module')} · ${plural(bucket.entries.reduce((count, item) => count + item.files.length, 0), 'document')}`;
  if (bucket.editing !== null) return 'Save or cancel your edits to continue.';
  if (bucket.hasDraft) return 'Add this module to your bucket to continue.';
  if (!bucket.entries.length) return 'Add at least one module to get started.';
  return `${plural(bucket.entries.length, 'module')} ready. Add another or continue.`;
}
function reviewFile(file) {
  if (!previews.has(file)) previews.set(file, URL.createObjectURL(file));
  const pdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
  return `<li><a class="review-file" href="${previews.get(file)}" target="_blank" rel="noopener" aria-label="Preview ${e(file.name)} (opens in a new tab)"><span class="review-thumbnail">${pdf ? icon('file') : `<img src="${previews.get(file)}" alt="">`}</span><span class="review-file-copy"><strong>${e(file.name)}</strong><small>${pdf ? 'PDF document' : 'Image'} · ${file.size < 1024*1024 ? `${Math.max(1, Math.round(file.size/1024))} KB` : `${(file.size/1024/1024).toFixed(1)} MB`}</small></span><span class="preview-label">Preview ↗</span></a></li>`;
}
export function inputView(project) {
  if (project) { bucket.name = project.name; bucket.weekCount = String(project.week_count); }
  cleanPreviews();
  const editing = bucket.editing !== null;
  const documentCount = bucket.entries.reduce((count, item) => count + item.files.length, 0);
  if (!project) bucket.weekCount = '14';
  const trimesterField = `<div class="trimester-line"><label for="trimester-name">Trimester name<input id="trimester-name" name="name" maxlength="${inputLimits.project_name_length}" required placeholder="e.g. Year 1, Trimester 1" value="${e(bucket.name)}" ${project ? 'readonly' : ''}></label><span class="term-caption-small">${bucket.weekCount} teaching weeks</span></div>`;
  const reviewAction = `<div class="bucket-footer"><p id="build-hint">${buildHint()}</p><button type="button" class="primary build-schedule" data-action="input-review" data-disabled="${!bucket.canBuild}" ${bucket.canBuild ? '' : 'disabled'}>Review documents${icon('arrow')}</button><p class="draft-guidance">Draft stays in this tab. Refreshing clears it.</p></div>`;
  return `<section class="input-workspace ${reviewing ? 'is-reviewing' : ''}" aria-labelledby="input-title">
    <ol class="intake-stages" aria-label="Submission steps"><li ${reviewing ? 'class="stage-complete"' : 'aria-current="step"'}><span>${reviewing ? icon('check') : '01'}</span> Add your modules</li><li ${reviewing ? 'aria-current="step"' : ''}><span>02</span> Review documents</li><li><span>03</span> Get your schedule</li></ol>
    <div class="intake-intro"><div class="input-heading"><h1 id="input-title" tabindex="-1">${reviewing ? 'Everything in order?' : 'Build your trimester'}</h1><p>${reviewing ? 'Check your modules and open any file to make sure it’s the right one.' : 'Add each module and its assessment briefs, then review them together.'}</p></div>${reviewing ? trimesterField : ''}</div>
    <div class="input-grid" ${reviewing ? 'hidden' : ''}>
      <section class="module-editor" aria-labelledby="editor-title"><div class="panel-heading"><div><p class="panel-kicker">MODULE ${String(editing ? bucket.entries.findIndex(item => item.id === bucket.editing) + 1 : bucket.entries.length + 1).padStart(2,'0')}</p><h2 id="editor-title">${editing ? 'Update your module' : bucket.entries.length ? 'Add another module' : 'Add your first module'}</h2></div><span class="editor-tag">${editing ? 'Editing' : 'New module'}</span></div>
        <form id="module-form"><div class="module-fields"><label for="module-title">Module title<input id="module-title" name="module-title" aria-describedby="input-error" value="${e(bucket.current.title)}" required maxlength="${inputLimits.module_title_length}" placeholder="e.g. INF1103 · Programming Fundamentals" autocomplete="off"></label><label for="module-credit">Credits<input id="module-credit" name="module-credit" aria-describedby="input-error" type="number" min="1" max="${inputLimits.credit}" step="1" required value="${e(bucket.current.credit)}"></label></div>
          <div class="screenshot-heading"><label for="module-images">Assessment documents</label><span id="file-count">${plural(bucket.current.files.length, 'file')}</span></div>
          <label class="screenshot-drop" id="screenshot-drop" for="module-images"><input id="module-images" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" multiple aria-describedby="file-help input-error"><span class="upload-symbol">${icon('upload')}</span><strong>Drop your briefs here</strong><span class="upload-browse">or choose files ${icon('arrow')}</span><small id="file-help">PDF, PNG or JPG · ${sizeLabel(inputLimits.document_bytes)} each<br> ${sizeLabel(inputLimits.request_bytes)} complete upload</small></label>
          <ul class="screenshot-files" id="screenshot-files" aria-label="Selected documents">${fileList()}</ul>
          <p class="input-error" id="input-error" role="alert" ${inputError ? '' : 'hidden'}>${e(inputError)}</p>
          <div class="editor-actions"><button type="button" data-action="${editing ? 'input-cancel' : 'input-clear'}" class="editor-secondary">${editing ? 'Cancel edits' : 'Clear form'}</button>${editing ? '<button type="button" data-action="input-remove" class="remove-from-bucket" aria-label="Remove this module from bucket">Remove module</button>' : ''}<button type="submit" class="primary">${editing ? 'Save changes' : 'Add module'}${icon(editing ? 'check' : 'plus')}</button></div>
        </form>
      </section>
      <aside class="module-bucket" aria-labelledby="bucket-title">${reviewing ? '' : trimesterField}<div class="panel-heading"><h2 id="bucket-title">Your modules <span class="bucket-count">${bucket.entries.length}</span></h2><span class="bucket-total">${plural(documentCount,'document')}</span></div><p class="bucket-description">${bucket.entries.length ? 'All together. Select a module to make changes.' : 'Build your collection, one module at a time.'}</p><div class="bucket-content" tabindex="0" role="region" aria-label="Modules in your bucket">${bucketCards()}</div><div class="bucket-notice" role="status" aria-live="polite">${e(notice)}${bucket.removed ? '<button type="button" data-action="input-undo">Undo removal</button>' : ''}</div>${reviewing ? '' : reviewAction}</aside>
    </div>
    ${reviewing ? `<section class="submission-review" aria-label="Submission review"><div class="review-list-heading"><h2>Documents to include</h2><span>${plural(bucket.entries.length,'module')}</span></div>${bucket.entries.map((item,index) => `<article><header><span class="review-module-number">${String(index+1).padStart(2,'0')}</span><div><h2>${e(item.title)}</h2><p>${item.credit} credits · ${plural(item.files.length,'document')}</p></div><button type="button" data-action="input-edit" data-id="${item.id}" aria-label="Edit ${e(item.title)}" class="text-button">${icon('edit')} Edit</button></header><ul>${item.files.map(reviewFile).join('')}</ul></article>`).join('')}</section>` : ''}
    ${reviewing ? `<div class="input-bottom"><p class="panel-kicker">READY WHEN YOU ARE</p><h2>Your next ${bucket.weekCount} weeks,<br>in one place.</h2><dl class="review-totals"><div><dt>Modules</dt><dd>${bucket.entries.length}</dd></div><div><dt>Documents</dt><dd>${documentCount}</dd></div><div><dt>Teaching weeks</dt><dd>${bucket.weekCount}</dd></div></dl><p class="review-note">Submitting locks these documents. To change them afterwards, start a new trimester.</p><p id="build-hint">${buildHint()}</p><button type="button" class="primary build-schedule" data-action="build-schedule" data-disabled="${!bucket.canBuild}" ${bucket.canBuild ? '' : 'disabled'}>Build assessment schedule${icon('arrow')}</button><button type="button" data-action="input-back" class="review-back">Back to modules</button></div>` : ''}
  </section>`;
}

export function showInputError(message) {
  inputError = message;
  const element = document.querySelector('#input-error');
  if (element) { element.textContent = message; element.hidden = !message; }
}
function refreshInputDetails() {
  cleanPreviews();
  document.querySelector('#screenshot-files').innerHTML = fileList();
  document.querySelector('#file-count').textContent = plural(bucket.current.files.length, 'file');
  document.querySelector('#build-hint').textContent = buildHint();
  const build = document.querySelector('.build-schedule');
  build.dataset.disabled = String(!bucket.canBuild);
  build.disabled = !bucket.canBuild;
}
export function handleInputChange(event) {
  const field = event.target;
  if (field.id === 'trimester-name') bucket.name = field.value;
  if (field.id === 'week-count') bucket.weekCount = field.value;
  if (field.id === 'module-title') bucket.current.title = field.value;
  if (field.id === 'module-credit') bucket.current.credit = field.value;
  if (!['trimester-name', 'week-count', 'module-title', 'module-credit'].includes(field.id)) return;
  showInputError('');
  refreshInputDetails();
}
export function addInputFiles(files) {
  try { bucket.addFiles(files); showInputError(''); refreshInputDetails(); }
  catch (error) { showInputError(error.message); }
}
export function saveInputModule(redraw) {
  try {
    const editing = bucket.editing !== null;
    const saved = bucket.save();
    notice = `${saved.title} ${editing ? 'updated' : 'added to your bucket'}.`;
    inputError = '';
    redraw();
    document.querySelector(reviewing ? '#input-title' : '#module-title')?.focus({ preventScroll: true });
  } catch (error) { showInputError(error.message); }
}
export function handleInputAction(target, redraw) {
  const action = target.dataset.action;
  if (!action.startsWith('input-')) return false;
  try {
    inputError = '';
    if (action === 'input-edit') { reviewing = false; bucket.edit(Number(target.dataset.id)); }
    if (action === 'input-review') { if (!document.querySelector('#trimester-name').reportValidity()) return true; bucket.submission(); reviewing = true; }
    if (action === 'input-back') reviewing = false;
    if (action === 'input-cancel') bucket.cancel();
    if (action === 'input-clear') bucket.draft = freshModule();
    if (action === 'input-remove') { bucket.remove(); notice = 'Module removed from your bucket.'; }
    if (action === 'input-undo') { bucket.undo(); notice = 'Module restored to your bucket.'; }
    if (action === 'input-remove-file') {
      bucket.current.files.splice(Number(target.dataset.index), 1);
      showInputError('');
      refreshInputDetails();
      const remaining = document.querySelectorAll('[data-action="input-remove-file"]');
      (remaining[Math.min(Number(target.dataset.index), remaining.length - 1)] || document.querySelector('#module-images'))?.focus();
      return true;
    }
    redraw();
    document.querySelector(reviewing ? '#input-title' : '#module-title')?.focus({ preventScroll: true });
  } catch (error) { showInputError(error.message); }
  return true;
}
