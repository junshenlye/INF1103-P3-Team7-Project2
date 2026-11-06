import { escape as e } from './model.js';

const freshModule = () => ({ title: '', credit: '6', files: [] });
const MAX_TOTAL = 49 * 1024 * 1024;
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
    if (incoming.some(file => !/\.(png|jpe?g)$/i.test(file.name) || (file.type && !['image/png', 'image/jpeg'].includes(file.type)))) {
      throw new Error('Choose PNG or JPG screenshots. Other file types are not supported.');
    }
    if (incoming.some(file => file.size > 10 * 1024 * 1024 || file.size === 0)) {
      throw new Error('Each screenshot must be a non-empty image of 10 MB or less.');
    }
    const unique = new Map(this.current.files.map(file => [fileKey(file), file]));
    incoming.forEach(file => unique.set(fileKey(file), file));
    const filesAfter = [...unique.values()];
    const otherSize = this.entries.filter(item => item.id !== this.editing).reduce((sum, item) => sum + item.files.reduce((bytes, file) => bytes + file.size, 0), 0);
    const pendingSize = this.editing === null ? 0 : this.draft.files.reduce((sum, file) => sum + file.size, 0);
    if (otherSize + pendingSize + filesAfter.reduce((sum, file) => sum + file.size, 0) > MAX_TOTAL) {
      throw new Error('Your screenshots exceed 49 MB in total. Remove a file or choose smaller images.');
    }
    this.current.files = filesAfter;
  }
  save() {
    const item = this.current;
    const title = item.title.trim();
    if (!title) throw new Error('Give this module a title before adding it to your bucket.');
    if (title.length > 200) throw new Error('Keep the module title within 200 characters.');
    if (!Number.isInteger(Number(item.credit)) || Number(item.credit) < 1) throw new Error('Enter a whole number of credits, starting from 1.');
    if (!item.files.length) throw new Error('Add at least one assessment screenshot for this module.');
    if (this.entries.some(entry => entry.id !== this.editing && entry.title.toLowerCase() === title.toLowerCase())) {
      throw new Error('This module is already in your bucket. Use a different title or edit the existing module.');
    }
    const combinedSize = this.entries.filter(entry => entry.id !== this.editing).reduce((sum, entry) => sum + entry.files.reduce((bytes, file) => bytes + file.size, 0), 0) + item.files.reduce((sum, file) => sum + file.size, 0);
    if (combinedSize > MAX_TOTAL) throw new Error('Keep the total upload within 49 MB.');
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
    if (this.entries.some(item => item.title.toLowerCase() === this.removed.item.title.toLowerCase())) {
      throw new Error('A module now uses this title. Rename it before restoring the removed module.');
    }
    if (this.totalSize + this.removed.item.files.reduce((sum, file) => sum + file.size, 0) + this.draft.files.reduce((sum, file) => sum + file.size, 0) + (this.editor ? this.editor.files.reduce((sum, file) => sum + file.size, 0) - this.entries.find(item => item.id === this.editing).files.reduce((sum, file) => sum + file.size, 0) : 0) > MAX_TOTAL) {
      throw new Error('Restoring this module would exceed 49 MB. Remove some screenshots first.');
    }
    this.entries.splice(this.removed.index, 0, this.removed.item);
    this.removed = null;
  }
  submission() {
    if (!this.canBuild) throw new Error('Add your current module to the bucket, or cancel its changes, before continuing.');
    if (this.totalSize > MAX_TOTAL) throw new Error('Keep the total upload within 49 MB.');
    if (!this.name.trim()) throw new Error('Name your trimester before continuing.');
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
let inputError = '';
function cleanPreviews() {
  const kept = new Set([...bucket.entries.flatMap(item => item.files), ...bucket.draft.files, ...(bucket.editor?.files || []), ...(bucket.removed?.item.files || [])]);
  for (const [file, url] of previews) if (!kept.has(file)) { URL.revokeObjectURL(url); previews.delete(file); }
}
export function resetInput() { bucket.reset(); notice = ''; inputError = ''; cleanPreviews(); }

function fileList() {
  return bucket.current.files.map((file, index) => {
    if (!previews.has(file)) previews.set(file, URL.createObjectURL(file));
    return `<li><img src="${previews.get(file)}" alt=""><span><strong>${e(file.name)}</strong><small>${file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`}</small></span><button type="button" class="icon-button" data-action="input-remove-file" data-index="${index}" aria-label="Remove ${e(file.name)}">${icon('close')}</button></li>`;
  }).join('');
}
function bucketCards() {
  if (!bucket.entries.length) return `<div class="bucket-empty"><div class="empty-stack" aria-hidden="true"><i></i><i></i><i>${icon('check')}</i></div><h3>A little order starts here.</h3><p>Add your first module using the form.<br>We’ll keep it neatly stacked here.</p></div>`;
  return `<ol class="bucket-list">${bucket.entries.map((item, index) => `<li class="bucket-card ${bucket.editing === item.id ? 'is-editing' : ''}"><button type="button" class="bucket-open" data-action="input-edit" data-id="${item.id}" aria-label="Edit ${e(item.title)}" ${bucket.editing === item.id ? 'aria-current="true"' : ''}><span class="module-number">${String(index + 1).padStart(2, '0')}</span><span class="bucket-card-copy"><strong>${e(item.title)}</strong><small>${item.credit} credits <span>·</span> ${plural(item.files.length, 'screenshot')}</small></span><span class="bucket-edit">${icon(bucket.editing === item.id ? 'edit' : 'check')}<span>${bucket.editing === item.id ? 'Editing' : 'Edit'}</span></span></button></li>`).join('')}</ol>`;
}
function buildHint() {
  if (bucket.editing !== null) return 'Save or cancel your edits to continue.';
  if (bucket.hasDraft) return 'Add this module to your bucket to continue.';
  if (!bucket.entries.length) return 'Add at least one module to get started.';
  return `${plural(bucket.entries.length, 'module')} ready. Add another or continue.`;
}
export function inputView(project) {
  if (project) bucket.name = project.name;
  cleanPreviews();
  const editing = bucket.editing !== null;
  return `<section class="input-workspace" aria-labelledby="input-title">
    <div class="input-heading"><div><h1 id="input-title">Your modules. <em>All together.</em></h1><p>One module at a time. A clearer trimester ahead.</p></div></div>
    <div class="trimester-line"><label for="trimester-name">Trimester</label><input id="trimester-name" name="name" maxlength="150" required placeholder="e.g. Year 1, Trimester 1" value="${e(bucket.name)}" ${project ? 'readonly' : ''}><span class="session-note"><span></span>Draft in this tab</span></div>
    <div class="input-grid">
      <section class="module-editor" aria-labelledby="editor-title"><div class="panel-heading"><div><span class="panel-kicker">${editing ? 'BACK ON THE DESK' : 'ON YOUR DESK'}</span><h2 id="editor-title">${editing ? 'Edit module' : bucket.entries.length ? 'Add another module' : 'Add your first module'}</h2></div><span class="editor-mark" aria-hidden="true">${icon(editing ? 'edit' : 'plus')}</span></div>
        <form id="module-form"><div class="module-fields"><label for="module-title">Module title<input id="module-title" name="module-title" value="${e(bucket.current.title)}" required maxlength="200" placeholder="e.g. INF1103 · Programming Fundamentals" autocomplete="off"></label><label for="module-credit">Credits<input id="module-credit" name="module-credit" type="number" min="1" step="1" required value="${e(bucket.current.credit)}"></label></div>
          <div class="screenshot-heading"><label for="module-images">Assessment screenshots</label><span id="file-count">${plural(bucket.current.files.length, 'file')}</span></div>
          <label class="screenshot-drop" id="screenshot-drop" for="module-images"><input id="module-images" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" multiple aria-describedby="file-help"><span class="upload-symbol">${icon('upload')}</span><strong>Drop screenshots here, or <u>browse files</u></strong><span>Include the assessment names, weightings and weeks.</span><small id="file-help">PNG or JPG · up to 10 MB each · 49 MB total</small></label>
          <ul class="screenshot-files" id="screenshot-files" aria-label="Selected screenshots">${fileList()}</ul>
          <p class="input-error" id="input-error" role="alert" ${inputError ? '' : 'hidden'}>${e(inputError)}</p>
          <div class="editor-actions"><button type="button" data-action="${editing ? 'input-cancel' : 'input-clear'}" class="editor-secondary">${editing ? 'Cancel edits' : 'Clear form'}</button>${editing ? '<button type="button" data-action="input-remove" class="remove-from-bucket" aria-label="Remove this module from bucket">Remove module</button>' : ''}<button type="submit" class="primary">${editing ? 'Save changes' : 'Add to bucket'}${icon(editing ? 'check' : 'arrow')}</button></div>
        </form>
      </section>
      <aside class="module-bucket" aria-labelledby="bucket-title"><div class="panel-heading"><div><span class="panel-kicker">READY WHEN YOU ARE</span><h2 id="bucket-title">Your bucket <span class="bucket-count">${bucket.entries.length}</span></h2></div><span class="bucket-symbol" aria-hidden="true">${icon('file')}</span></div><p class="bucket-description">Everything you’ve added. Open any module to edit.</p>
        <div class="bucket-content" tabindex="0" role="region" aria-label="Modules in your bucket">${bucketCards()}</div>
        <div class="bucket-notice" role="status" aria-live="polite">${e(notice)}${bucket.removed ? '<button type="button" data-action="input-undo">Undo removal</button>' : ''}</div>
        <div class="bucket-bottom"><span>${icon('check')}Kept together, ready for the next step.</span><small>Drafts stay here until you refresh or leave this page.</small></div>
      </aside>
    </div>
    <div class="input-bottom"><div><span class="next-step">UP NEXT</span><strong>Your assessment schedule</strong><p id="build-hint">${buildHint()}</p></div><button type="button" class="primary build-schedule" data-action="build-schedule" data-disabled="${!bucket.canBuild}" ${bucket.canBuild ? '' : 'disabled'}>Build assessment schedule${icon('arrow')}</button></div>
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
  const build = document.querySelector('[data-action="build-schedule"]');
  build.dataset.disabled = String(!bucket.canBuild);
  build.disabled = !bucket.canBuild;
}
export function handleInputChange(event) {
  const field = event.target;
  if (field.id === 'trimester-name') bucket.name = field.value;
  if (field.id === 'module-title') bucket.current.title = field.value;
  if (field.id === 'module-credit') bucket.current.credit = field.value;
  if (!['trimester-name', 'module-title', 'module-credit'].includes(field.id)) return;
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
    document.querySelector('#module-title')?.focus({ preventScroll: true });
  } catch (error) { showInputError(error.message); }
}
export function handleInputAction(target, redraw) {
  const action = target.dataset.action;
  if (!action.startsWith('input-')) return false;
  try {
    inputError = '';
    if (action === 'input-edit') bucket.edit(Number(target.dataset.id));
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
    document.querySelector('#module-title')?.focus({ preventScroll: true });
  } catch (error) { showInputError(error.message); }
  return true;
}
