// Polya front end: selection mode, editors, and live updates over server-sent events.
(() => {
  const D = document.body.dataset.dialog;
  if (!D) return;
  const base = `/d/${encodeURIComponent(D)}`;
  const $ = (s, el = document) => el.querySelector(s);
  const msgsEl = $('#msgs');
  const byId = id => document.getElementById('m-' + id);
  const all = () => [...msgsEl.querySelectorAll(':scope > .msg')];
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);

  let selected = null;      // id of the selected message
  let editing = null;       // {id, part: 'content'|'reply', cm}
  let wantSelect = null;    // id to select as soon as it shows up
  let ctype = 'code';       // type of the next message from the bottom editor

  async function post(body) {
    const r = await fetch(base + '/do', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({error: 'Bad response from server'}));
    if (j.error) toast(j.error);
    return j;
  }

  function toast(text) {
    const t = document.createElement('div');
    t.className = 'toast'; t.textContent = text;
    document.body.append(t);
    setTimeout(() => t.remove(), 4000);
  }

  // ---------------------------------------------------------------- selection
  function select(id, scroll = true) {
    const el = id && byId(id);
    if (!el) return;
    all().forEach(e => e.classList.toggle('sel', e === el));
    selected = id;
    if (scroll) el.scrollIntoView({block: 'nearest'});
  }
  function step(d) {
    const ms = all();
    if (!ms.length) return;
    let i = ms.findIndex(e => e.dataset.id === selected);
    i = i < 0 ? (d > 0 ? 0 : ms.length - 1) : Math.max(0, Math.min(ms.length - 1, i + d));
    select(ms[i].dataset.id);
  }
  function neighbour(id, d) {
    const ms = all(), i = ms.findIndex(e => e.dataset.id === id);
    return ms[i + d] ? ms[i + d].dataset.id : null;
  }
  const typeOf = id => byId(id)?.dataset.type;

  // ---------------------------------------------------------------- editors
  const modeFor = t => t === 'code' ? 'python' : (t === 'raw' ? null : 'markdown');

  async function kernelHint(cm) {
    const cur = cm.getCursor(), code = cm.getValue(), pos = cm.indexFromPos(cur);
    const r = await fetch(base + '/complete', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code, pos})}).then(r => r.json()).catch(() => null);
    if (!r || !r.matches || !r.matches.length) return null;
    return {list: r.matches, from: cm.posFromIndex(r.start), to: cur};
  }
  kernelHint.async = false;

  function makeEditor(host, value, type, keys) {
    const cm = CodeMirror(host, {
      value, mode: modeFor(type), lineWrapping: true, indentUnit: 4, tabSize: 4, viewportMargin: Infinity,
      autoCloseBrackets: true, matchBrackets: true, lineNumbers: false,
      extraKeys: Object.assign({
        Tab(cm) {
          if (cm.somethingSelected()) return cm.indentSelection('add');
          const cur = cm.getCursor(), before = cm.getLine(cur.line).slice(0, cur.ch);
          if (cm.getOption('mode') === 'python' && /[\w.]$/.test(before)) cm.showHint({hint: kernelHint, completeSingle: true});
          else cm.replaceSelection(' '.repeat(4 - (cur.ch % 4)));
        },
        'Shift-Tab': cm => cm.indentSelection('subtract'),
        'Cmd-/': 'toggleComment', 'Ctrl-/': 'toggleComment',
        F12: cm => showDef(nameAt(cm.getValue(), cm.indexFromPos(cm.getCursor())), moduleOf(cm.getWrapperElement())),
      }, keys),
    });
    cm.on('mousedown', (cm, e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      showDef(nameAt(cm.getValue(), cm.indexFromPos(cm.coordsChar({left: e.clientX, top: e.clientY}))), moduleOf(cm.getWrapperElement()));
    });
    return cm;
  }

  async function startEdit(id, part = 'content') {
    if (editing) await endEdit(false);
    if (!byId(id) || (part === 'reply' && typeOf(id) !== 'prompt')) return;
    const raw = await fetch(`${base}/msg/${id}/raw`).then(r => r.json());
    if (raw.error) return toast(raw.error);
    const el = byId(id);   // look it up after the fetch: a live update may have replaced the element meanwhile
    if (!el || editing) return;
    select(id);
    const slot = $(part === 'reply' ? '.mout' : '.min', el);
    const host = document.createElement('div');
    host.className = 'editor';
    slot.hidden = true;
    slot.after(host);
    el.classList.add('editing');
    const cm = makeEditor(host, part === 'reply' ? raw.reply : raw.content, part === 'reply' ? 'note' : raw.type, {
      Esc: () => endEdit(false),
      'Ctrl-Enter': () => endEdit(true), 'Cmd-Enter': () => endEdit(true),
      'Shift-Enter': () => endEdit(true, true),
    });
    editing = {id, part, cm, host, slot};
    cm.focus();
    cm.setCursor(cm.lineCount(), 0);
  }

  async function endEdit(run, advance) {
    if (!editing) return;
    const {id, part, cm, host, slot} = editing;
    editing = null;
    const body = {op: 'update', id};
    body[part] = cm.getValue();
    if (run && part === 'content') body.run = true;
    host.remove(); slot.hidden = false;
    byId(id)?.classList.remove('editing');
    await post(body);
    if (advance) step(1);
    msgsEl.focus();
  }

  // ---------------------------------------------------------------- go to definition
  // The dotted name around a position: clicking `join` in `os.path.join(` gives `os.path.join`, clicking `os` gives `os`.
  function nameAt(text, pos) {
    let a = pos, b = pos;
    while (a > 0 && /[\w.]/.test(text[a - 1])) a--;
    while (b < text.length && /\w/.test(text[b])) b++;
    return text.slice(a, b).replace(/^[.\d]+/, '');
  }
  function nameAtPoint(pre, x, y) {
    const r = document.caretRangeFromPoint ? document.caretRangeFromPoint(x, y) : null;
    if (!r || !pre.contains(r.startContainer)) return '';
    const upto = document.createRange();
    upto.setStart(pre, 0); upto.setEnd(r.startContainer, r.startOffset);
    return nameAt(pre.textContent, upto.toString().length);
  }
  let defStack = [], defCur = null;
  async function showDef(name, ctx = '', push = true) {
    if (!name) return;
    const d = await fetch(base + '/definition', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, ctx})}).then(r => r.json()).catch(() => ({error: 'Lookup failed'}));
    if (d.error) return toast(d.error);
    if (push && defCur) defStack.push(defCur);
    d.ctxUsed = ctx;
    defCur = d;
    $('#defn').hidden = false;
    $('#dback').disabled = !defStack.length;
    $('#dtitle').textContent = `${d.qualname}${d.signature || ''}`;
    const meta = $('#dmeta');
    meta.replaceChildren();
    const where = document.createElement('div'); where.className = 'path';
    where.textContent = `${d.kind}${d.module ? ' in ' + d.module : ''}  ·  ${d.file ? d.file + ':' + d.line : 'no source file'}`;
    meta.append(where);
    if (d.note) { const n = document.createElement('div'); n.className = 'dnote'; n.textContent = d.note; meta.append(n); }
    const hint = document.createElement('div'); hint.textContent = 'Ctrl+click (or right-click) a name in this source to follow it further. ';
    if (d.open) { const a = document.createElement('a'); a.href = d.open; a.textContent = 'Open in VS Code'; a.title = `Open ${d.file} at line ${d.line} in your editor`; hint.append(a); }
    meta.append(hint);
    $('#dcode').textContent = d.linkable ? 'Bring into dialog' : 'Insert as code';
    $('#dcode').title = d.linkable ? 'Add this as a code cell linked to its file: run it, change it, see the diff, write it back' : 'Copy this source into a code cell';
    $('#dbody').innerHTML = d.html || '';
    if (!d.html && d.doc) { const p = document.createElement('pre'); p.textContent = d.doc; $('#dbody').append(p); }
    $('#dcode').disabled = $('#dnote').disabled = !d.source;
    $('#dbody').scrollTop = 0;
  }
  function closeDef() { $('#defn').hidden = true; defStack = []; defCur = null; }
  async function insertDef(asNote) {
    const d = defCur;
    if (!d || !d.source) return;
    if (!asNote && d.linkable) {       // a real function or class in a file: bring it in linked, not as a loose copy
      const r = await post({op: 'add_source', file: d.file, qualname: d.qualname, after: selected || undefined});
      if (r.id) { wantSelect = r.id; if (byId(r.id)) select(r.id); toast('Brought in, linked to ' + (d.rel || d.file)); }
      return;
    }
    const where = `${d.file || 'unknown file'}:${d.line}`;
    const content = asNote
      ? `Definition of \`${d.name}\` (${where}):\n\n\`\`\`python\n${d.source.replace(/\n$/, '')}\n\`\`\``
      : `# Copy of ${d.module ? d.module + '.' : ''}${d.qualname} from ${where}\n# Running this redefines the name in this kernel only; the file is not changed.\n${d.source.replace(/\n$/, '')}`;
    const body = {op: 'add', type: asNote ? 'note' : 'code', content};
    if (selected) body.after = selected;
    const r = await post(body);
    if (r.id) { wantSelect = r.id; if (byId(r.id)) select(r.id); toast(asNote ? 'Added as a note' : 'Added as a code message (not run)'); }
  }

  // ---------------------------------------------------------------- cells linked to files
  const moduleOf = el => el.closest('.msg')?.querySelector('.f-src')?.dataset.module || '';
  const modal = $('#modal'), mbox = $('#mbox');
  function openModal(...nodes) { mbox.replaceChildren(...nodes); modal.hidden = false; }
  function closeModal() { modal.hidden = true; mbox.replaceChildren(); }
  function el(tag, props = {}, ...kids) { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; }
  function diffNode(text) {
    const pre = el('pre', {className: 'diff'});
    if (!text) { pre.textContent = '(no differences)'; return pre; }
    for (const line of text.split('\n')) {
      const c = line.startsWith('+++') || line.startsWith('---') ? 'dh' : line.startsWith('@@') ? 'dh' : line.startsWith('+') ? 'da' : line.startsWith('-') ? 'dd' : '';
      pre.append(el('span', {className: c, textContent: line + '\n'}));
    }
    return pre;
  }
  async function applyOne(id, force) {
    const r = await post({op: 'src_apply', id, force});
    if (r.written) toast('Written to ' + r.written);
    return r;
  }
  // One cell: what would be written, with the buttons that act on it.
  async function showDiff(id) {
    const d = await post({op: 'src_diff', id});
    if (d.error) return;
    const btns = el('div', {className: 'mbtns'});
    const can = ['edited', 'new', 'conflict'].includes(d.status);
    if (can) btns.append(el('button', {className: 'primary', textContent: d.status === 'conflict' ? 'Overwrite the file with this cell' : 'Write to file',
      onclick: async () => { const r = await applyOne(id, d.status === 'conflict'); if (!r.error) closeModal(); }}));
    if (d.status !== 'new') btns.append(el('button', {textContent: "Revert cell to the file's version", onclick: async () => { await post({op: 'src_revert', id}); closeModal(); }}));
    btns.append(el('button', {textContent: 'Close', onclick: closeModal}));
    const note = {disk: 'The file changed after you brought this in. Nothing here needs writing; revert to take the new version.',
                  conflict: 'Both the cell and the file changed since you brought this in. Read the diff before choosing.'}[d.status];
    openModal(el('h2', {textContent: d.name}), el('div', {className: 'fine', textContent: d.label + (note ? ' — ' + note : '')}), diffNode(d.diff), btns);
  }
  // Every linked cell that differs from its file.
  async function showChanges() {
    const r = await fetch(base + '/changes').then(r => r.json());
    const head = el('h2', {textContent: 'Changes to write back'});
    if (!r.items.length) return openModal(head, el('p', {className: 'fine', textContent: r.linked ? `All ${r.linked} linked cells match their files.` : 'No cells in this dialog are linked to files yet. Ctrl+click a name and choose "Bring into dialog", or use "→ file…" on a code cell.'}), el('div', {className: 'mbtns'}, el('button', {textContent: 'Close', onclick: closeModal})));
    const rows = [], files = {};
    for (const it of r.items) (files[it.file] ||= []).push(it);
    const list = el('div', {className: 'chglist'});
    for (const [file, items] of Object.entries(files)) {
      list.append(el('h3', {textContent: file}));
      for (const it of items) {
        const writable = ['edited', 'new'].includes(it.status);
        const cb = el('input', {type: 'checkbox', checked: writable, disabled: !writable});
        rows.push([cb, it]);
        const where = it.status === 'new' ? ` (goes ${it.after ? 'after ' + it.after : 'at the end of the file'})` : '';
        const go = el('a', {href: '#', textContent: 'show cell', onclick: e => { e.preventDefault(); closeModal(); select(it.id); }});
        list.append(el('details', {open: items.length < 4}, el('summary', {}, cb, el('b', {textContent: ' ' + it.qualname}), el('span', {className: 's-' + it.status, textContent: ' · ' + it.label + where + ' '}), go), diffNode(it.diff)));
      }
    }
    const apply = el('button', {className: 'primary', textContent: 'Write selected to files', onclick: async () => {
      let n = 0;
      for (const [cb, it] of rows) if (cb.checked) { const x = await post({op: 'src_apply', id: it.id}); if (x.error) break; n++; }
      if (n) toast(`Wrote ${n} change${n === 1 ? '' : 's'}`);
      showChanges();
    }});
    openModal(head, el('div', {className: 'fine', textContent: `Project: ${r.project || '(none: start Polya with --project)'}. Ticked items are written exactly as shown. Conflicts and files that changed on disk are never written from here; open the cell to decide.`}), list, el('div', {className: 'mbtns'}, apply, el('button', {textContent: 'Close', onclick: closeModal})));
  }
  // New code has no place in a file until you give it one.
  async function chooseTarget(id) {
    const info = await fetch(base + '/symbols').then(r => r.json());
    if (info.error) return toast(info.error);
    // Sensible default: the same file as the nearest linked cell above, right after that function.
    let dfile = '', dafter = '';
    for (let e = byId(id)?.previousElementSibling; e; e = e.previousElementSibling) {
      const f = e.querySelector('.f-src');
      if (f) { const [file, what] = f.textContent.split(' · '); dfile = file; dafter = /^(after |end of file)/.test(what) ? '' : what; break; }
    }
    const dl = el('datalist', {id: 'pyfiles'}, ...info.files.map(f => el('option', {value: f})));
    const file = el('input', {value: dfile, placeholder: 'path/inside/project.py', size: 50}); file.setAttribute('list', 'pyfiles');
    const after = el('select'), create = el('input', {type: 'checkbox'});
    const fill = async () => {
      const r = await fetch(`${base}/symbols?file=${encodeURIComponent(file.value)}`).then(r => r.json());
      after.replaceChildren(el('option', {value: '', textContent: 'at the end of the file'}), ...r.symbols.map(q => el('option', {value: q, textContent: 'after ' + q + (q.includes('.') ? '  (inside the class)' : '')})));
      if (r.symbols.includes(dafter)) after.value = dafter;
    };
    file.onchange = fill; await fill();
    const save = el('button', {className: 'primary', textContent: 'Set destination', onclick: async () => {
      const r = await post({op: 'src_target', id, file: file.value.trim(), after: after.value, create: create.checked});
      if (!r.error) { closeModal(); toast('Destination set. Nothing is written until you apply it.'); }
    }});
    openModal(el('h2', {textContent: 'Where should this code go?'}),
      el('p', {className: 'fine', textContent: 'This only records the destination on the cell. The file is written when you choose "→ file" or use Changes.'}),
      el('label', {className: 'frow'}, 'File ', file, dl), el('label', {className: 'frow'}, 'Position ', after),
      el('label', {className: 'frow'}, create, ' create the file if it does not exist'),
      el('div', {className: 'mbtns'}, save, el('button', {textContent: 'Unlink from file', onclick: async () => { await post({op: 'src_unlink', id}); closeModal(); }}), el('button', {textContent: 'Cancel', onclick: closeModal})));
    file.focus();
  }
  // Right-click a name -> Go to definition, as in an editor.
  const ctx = $('#ctxmenu');
  function showCtx(x, y, name, mod) {
    if (!name) return false;
    ctx.replaceChildren(el('button', {textContent: `Go to definition of ${name.length > 40 ? '…' + name.slice(-40) : name}`, onclick: () => { ctx.hidden = true; showDef(name, mod); }}));
    ctx.style.left = Math.min(x, innerWidth - 320) + 'px'; ctx.style.top = y + 'px'; ctx.hidden = false;
    return true;
  }
  document.addEventListener('click', () => { ctx.hidden = true; });
  document.addEventListener('contextmenu', e => {
    const cmEl = e.target.closest('.CodeMirror');
    if (cmEl && cmEl.CodeMirror.getOption('mode') === 'python') {
      const cm = cmEl.CodeMirror;
      if (showCtx(e.clientX, e.clientY, nameAt(cm.getValue(), cm.indexFromPos(cm.coordsChar({left: e.clientX, top: e.clientY}))), moduleOf(cmEl))) e.preventDefault();
      return;
    }
    const pre = e.target.closest('#msgs pre, #dbody pre');
    if (!pre || e.target.closest('.o-stream, .o-error, .o-result')) return;
    const mod = pre.closest('#dbody') ? (defCur && defCur.module) || '' : moduleOf(pre);
    if (showCtx(e.clientX, e.clientY, nameAtPoint(pre, e.clientX, e.clientY), mod)) e.preventDefault();
  });

  // ---------------------------------------------------------------- bottom editor
  const hints = {
    code: 'Python. Ctrl+Enter runs it.',
    note: 'Markdown note to yourself (the AI reads it too).',
    prompt: 'Ask the AI. It sees everything above. Alt+Enter keeps you in prompt mode.',
  };
  let composer;
  function setCType(t) {
    ctype = t;
    document.querySelectorAll('.ctype').forEach(b => b.classList.toggle('on', b.dataset.type === t));
    $('#composer').dataset.type = t;
    $('#chint').textContent = hints[t];
    $('#csend').textContent = t === 'code' ? 'Run' : (t === 'prompt' ? 'Ask' : 'Add');
    if (composer) composer.setOption('mode', modeFor(t));
  }
  async function submit(stay) {
    const content = composer.getValue();
    if (!content.trim()) return;
    const type = ctype;
    composer.setValue('');
    const r = await post({op: 'add', type, content, run: true});
    if (r.id) { wantSelect = r.id; if (byId(r.id)) select(r.id); }
    // "Default code": after asking the AI, the next thing you write is code, unless you said otherwise.
    if (type === 'prompt' && !stay) setCType('code');
  }

  // ---------------------------------------------------------------- clipboard (works across dialogs)
  async function copy(id, cut) {
    const raw = await fetch(`${base}/msg/${id}/raw`).then(r => r.json());
    if (raw.error) return;
    try { localStorage.setItem('polya-clip', JSON.stringify([raw])); } catch (e) {}
    if (cut) {
      const next = neighbour(id, 1) || neighbour(id, -1);
      await post({op: 'delete', id});
      if (next) select(next);
    } else toast('Copied');
  }
  async function paste() {
    let msgs = [];
    try { msgs = JSON.parse(localStorage.getItem('polya-clip') || '[]'); } catch (e) {}
    if (!msgs.length) return toast('Nothing to paste');
    const r = await post({op: 'paste', after: selected, msgs});
    if (r.ids && r.ids.length) { wantSelect = r.ids[r.ids.length - 1]; if (byId(wantSelect)) select(wantSelect); }
  }

  // ---------------------------------------------------------------- actions on a message
  async function act(name, id) {
    const el = byId(id);
    if (!el) return;
    const t = el.dataset.type;
    if (name === 'run') return (t === 'code' || t === 'prompt') ? post({op: 'run', id}) : null;
    if (name === 'edit') return startEdit(id, 'content');
    if (name === 'reply') return startEdit(id, 'reply');
    if (name === 'extract') {
      const r = await post({op: 'extract', id});
      if (r.ids && !r.ids.length) toast('No code blocks in this reply');
      else if (r.ids) { wantSelect = r.ids[0]; if (byId(wantSelect)) select(wantSelect); }
      return;
    }
    if (name === 'hide') return post({op: 'update', id, hidden: !el.classList.contains('is-hidden')});
    if (name === 'pin') return post({op: 'update', id, pinned: !el.classList.contains('is-pinned')});
    if (name === 'up' || name === 'down') return post({op: 'move', id, dir: name});
    if (name === 'delete') return copy(id, true);
    if (name === 'clear') return post({op: 'clear', id});
    if (name === 'diff' || name === 'apply') return showDiff(id);
    if (name === 'revert') { if (confirm("Throw away this cell's changes and take the file's version again?")) await post({op: 'src_revert', id}); return; }
    if (name === 'tofile') return chooseTarget(id);
  }
  async function addNear(where) {
    const body = {op: 'add', type: 'code', content: ''};
    if (selected) body[where] = selected;
    const r = await post(body);
    if (r.id) {
      const go = () => byId(r.id) ? startEdit(r.id) : setTimeout(go, 30);
      go();
    }
  }
  async function setType(id, type) {
    if (typeOf(id) === type) return;
    await post({op: 'update', id, type});
  }
  async function heading(id, level) {
    if (typeOf(id) !== 'note') return;
    const raw = await fetch(`${base}/msg/${id}/raw`).then(r => r.json());
    const lines = raw.content.split('\n');
    lines[0] = '#'.repeat(level) + ' ' + lines[0].replace(/^#+\s*/, '');
    await post({op: 'update', id, content: lines.join('\n')});
  }

  // ---------------------------------------------------------------- live updates
  function upsert(ev) {
    const tmp = document.createElement('div');
    tmp.innerHTML = ev.html;
    const neu = tmp.firstElementChild;
    let el = byId(ev.id);
    const near = msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 80;
    if (el && editing && editing.id === ev.id) {
      // Keep the open editor; refresh everything around it.
      $('.mhead', el).replaceWith($('.mhead', neu));
      const part = editing.part === 'content' ? '.mout' : '.min';
      $(part, el).replaceWith($(part, neu));
      el.className = neu.className + ' editing' + (selected === ev.id ? ' sel' : '');
    } else if (el) {
      if (selected === ev.id) neu.classList.add('sel');
      el.replaceWith(neu); el = neu;
    } else el = neu;
    const prev = ev.after ? byId(ev.after) : null;
    if (prev) { if (prev.nextElementSibling !== el) prev.after(el); }
    else if (ev.after === '' && msgsEl.firstElementChild !== el) msgsEl.prepend(el);
    else if (!el.isConnected) msgsEl.append(el);
    if (wantSelect === ev.id) { wantSelect = null; select(ev.id); }
    else if (near && !editing) msgsEl.scrollTop = msgsEl.scrollHeight;
    outline();
  }
  function remove(ev) {
    const el = byId(ev.id);
    if (!el) return;
    if (editing && editing.id === ev.id) editing = null;
    if (selected === ev.id) { const n = neighbour(ev.id, 1) || neighbour(ev.id, -1); el.remove(); if (n) select(n, false); else selected = null; }
    else el.remove();
    outline();
  }
  let wasBusy = false;
  function status(ev) {
    const k = $('#kstat');
    k.className = 'kstat ' + (ev.busy ? 'busy' : (ev.alive ? 'idle' : 'off'));
    $('#ktext').textContent = ev.busy ? 'working…' : (ev.alive ? 'kernel idle' : 'kernel not started');
    $('#ctx').textContent = `AI context ≈ ${ev.tokens.toLocaleString()} tokens`;
    const ban = $('#banner');
    ban.hidden = !ev.setup_error; ban.textContent = ev.setup_error || '';
    if (wasBusy && !ev.busy) refreshVars();
    wasBusy = ev.busy;
  }
  let connected = false;
  function connect() {
    const es = new EventSource(base + '/events');
    es.onopen = () => { if (connected === null) location.reload(); connected = true; };
    es.onerror = () => { if (connected) connected = null; $('#ktext').textContent = 'reconnecting…'; };
    es.onmessage = e => {
      const ev = JSON.parse(e.data);
      if (ev.op === 'upsert') upsert(ev);
      else if (ev.op === 'delete') remove(ev);
      else if (ev.op === 'status') status(ev);
    };
  }

  // ---------------------------------------------------------------- sidebar
  function outline() {
    const side = $('#side');
    if (side.hidden) return;
    const hs = [...msgsEl.querySelectorAll('.t-note .min h1, .t-note .min h2, .t-note .min h3')];
    $('#outline').replaceChildren(...hs.map(h => {
      const a = document.createElement('a');
      a.textContent = h.textContent; a.className = 'ol ol-' + h.tagName.toLowerCase(); a.href = '#';
      a.onclick = e => { e.preventDefault(); select(h.closest('.msg').dataset.id); };
      return a;
    }));
    if (!hs.length) $('#outline').textContent = 'No headings yet. Press 1–3 on a note.';
  }
  async function refreshVars() {
    if ($('#side').hidden) return;
    const r = await fetch(base + '/vars').then(r => r.json()).catch(() => null);
    if (!r || r.busy) return;
    const fill = (el, obj, empty) => {
      const rows = Object.entries(obj || {}).map(([k, v]) => {
        const d = document.createElement('div'); d.className = 'var';
        const n = document.createElement('b'); n.textContent = k;
        const s = document.createElement('span'); s.textContent = ' ' + v;
        d.append(n, s); return d;
      });
      el.replaceChildren(...rows);
      if (!rows.length) el.textContent = empty;
    };
    fill($('#vars'), r.vars, 'None yet. Run some code.');
    fill($('#funcs'), r.funcs, 'None yet.');
  }

  // ---------------------------------------------------------------- wiring
  msgsEl.tabIndex = 0;
  msgsEl.addEventListener('click', e => {
    const m = e.target.closest('.msg');
    if (!m) return;
    const b = e.target.closest('.act');
    if (b) { select(m.dataset.id, false); act(b.dataset.act, m.dataset.id); return; }
    if ((e.ctrlKey || e.metaKey) && e.target.closest('pre') && !e.target.closest('.editor')) {
      e.preventDefault();
      return showDef(nameAtPoint(e.target.closest('pre'), e.clientX, e.clientY), moduleOf(e.target));
    }
    if (e.target.closest('.editor, a, summary, details')) return;
    if (selected === m.dataset.id && !editing && !window.getSelection().toString() && e.target.closest('.min')) return startEdit(m.dataset.id);
    select(m.dataset.id, false);
  });
  msgsEl.addEventListener('dblclick', e => {
    const m = e.target.closest('.msg');
    if (!m || e.target.closest('.editor, .act')) return;
    startEdit(m.dataset.id, e.target.closest('.mout') && m.dataset.type === 'prompt' ? 'reply' : 'content');
  });

  document.addEventListener('keydown', e => {
    const help = $('#help');
    if (!help.hidden) { if (e.key === 'Escape' || e.key === '?') { help.hidden = true; e.preventDefault(); } return; }
    if (e.key === 'Escape' && !modal.hidden) { closeModal(); e.preventDefault(); return; }
    if (!modal.hidden) return;
    if (e.key === 'Escape' && !$('#defn').hidden && !e.target.closest('.CodeMirror')) { closeDef(); e.preventDefault(); return; }
    const mod = e.ctrlKey || e.metaKey;
    const typeKey = {KeyJ: 'code', KeyK: 'note', KeyL: 'prompt'}[e.code];
    const inEditor = e.target.closest('.CodeMirror, input, textarea, select');
    // Type switching works everywhere: Ctrl/Cmd+Shift+J/K/L, or Alt+J/K/L where the browser keeps the former for itself.
    if (typeKey && ((mod && e.shiftKey) || (e.altKey && !mod))) {
      e.preventDefault();
      if (e.target.closest('#composer') || (!selected && !editing)) setCType(typeKey);
      else if (editing) { const id = editing.id; endEdit(false).then(() => setType(id, typeKey)).then(() => startEdit(id)); }
      else setType(selected, typeKey);
      return;
    }
    if (inEditor) return;
    if (mod && e.key === 'Enter') { e.preventDefault(); if (selected) act('run', selected); return; }
    if (e.shiftKey && e.key === 'Enter') { e.preventDefault(); if (selected) { act('run', selected); step(1); } return; }
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); if (selected) act(e.key === 'ArrowUp' ? 'up' : 'down', selected); return; }
    if (mod || e.altKey) return;
    const k = e.key;
    const map = {
      ArrowDown: () => step(1), j: () => step(1), ArrowUp: () => step(-1), k: () => step(-1),
      Home: () => { const m = all()[0]; if (m) select(m.dataset.id); },
      End: () => { const ms = all(); if (ms.length) select(ms[ms.length - 1].dataset.id); },
      Enter: () => selected && startEdit(selected), n: () => selected && startEdit(selected, 'reply'),
      a: () => addNear('before'), b: () => addNear('after'),
      x: () => selected && copy(selected, true), c: () => selected && copy(selected, false), v: () => paste(),
      h: () => selected && act('hide', selected), p: () => selected && act('pin', selected),
      w: () => selected && typeOf(selected) === 'prompt' && act('extract', selected),
      Backspace: () => selected && act('clear', selected), Delete: () => selected && act('clear', selected),
      r: () => runAll('all'), A: () => runAll('above'), B: () => runAll('below'), R: () => restart(), S: () => post({op: 'stop'}),
      '/': () => composer.focus(), '?': () => { help.hidden = false; },
    };
    if (/^[1-6]$/.test(k) && selected) { e.preventDefault(); heading(selected, +k); return; }
    if (map[k]) { e.preventDefault(); map[k](); }
  });

  const modkey = e => document.body.classList.toggle('modkey', e.ctrlKey || e.metaKey);
  document.addEventListener('keydown', modkey); document.addEventListener('keyup', modkey); window.addEventListener('blur', () => document.body.classList.remove('modkey'));
  $('#dbody').addEventListener('click', e => {
    const pre = e.target.closest('pre');
    if (!pre || !(e.ctrlKey || e.metaKey) || !defCur) return;
    e.preventDefault();
    showDef(nameAtPoint(pre, e.clientX, e.clientY), defCur.module);
  });
  $('#dclose').onclick = closeDef;
  $('#dback').onclick = () => { const d = defStack.pop(); if (d) { defCur = null; showDef(d.name, d.ctxUsed || '', false); } };
  $('#dcode').onclick = () => insertDef(false);
  $('#dnote').onclick = () => insertDef(true);

  // Bulk runs only ever run code. Prompts keep their saved replies; unreviewed AI-written cells are left alone.
  async function runAll(scope) {
    if (scope !== 'all' && !selected) return;
    const r = await post({op: 'runall', scope, id: scope === 'all' ? undefined : selected});
    if (r.error) return;
    const what = {all: 'all', above: 'above', below: 'from here down'}[scope];
    let msg = `Running ${r.count} code message${r.count === 1 ? '' : 's'} (${what}). Prompts are not re-sent.`;
    if (r.skipped) msg += ` Skipped ${r.skipped} written by the AI that you have not run yourself.`;
    toast(msg);
  }

  function restart() { if (confirm('Restart the kernel? All variables will be lost.')) post({op: 'restart'}); }

  document.querySelectorAll('.ctype').forEach(b => b.onclick = () => { setCType(b.dataset.type); composer.focus(); });
  $('#csend').onclick = () => submit(false);
  $('#runall').onclick = () => runAll('all');
  $('#stop').onclick = () => post({op: 'stop'});
  $('#restart').onclick = restart;
  $('#mode').onchange = e => post({op: 'settings', mode: e.target.value});
  $('#dtools').onchange = e => post({op: 'settings', dialog_tools: e.target.checked});
  $('#ctools').onchange = e => post({op: 'settings', code_tools: e.target.checked});
  $('#model').onchange = e => post({op: 'settings', model: e.target.value});
  $('#export').onchange = e => { if (e.target.value) location.href = `${base}/export/${e.target.value}`; e.target.value = ''; };
  $('#helpbtn').onclick = () => { $('#help').hidden = false; };
  $('#helpclose').onclick = () => { $('#help').hidden = true; };
  $('#help').onclick = e => { if (e.target.id === 'help') e.target.hidden = true; };
  $('#chgbtn').onclick = showChanges;
  modal.onclick = e => { if (e.target === modal) closeModal(); };
  $('#sidetoggle').onclick = () => {
    const s = $('#side'); s.hidden = !s.hidden;
    try { localStorage.setItem('polya-side', s.hidden ? '' : '1'); } catch (e) {}
    outline(); refreshVars();
  };

  composer = makeEditor($('#ceditor'), '', 'code', {
    'Ctrl-Enter': () => submit(false), 'Cmd-Enter': () => submit(false), 'Shift-Enter': () => submit(false),
    'Alt-Enter': () => submit(true),
    Esc: cm => { cm.getInputField().blur(); msgsEl.focus(); if (!selected) step(-1); },
  });
  composer.setOption('placeholder', '');
  setCType('code');
  try { if (localStorage.getItem('polya-side')) $('#side').hidden = false; } catch (e) {}
  connect();
  outline(); refreshVars();
  const ms = all();
  if (ms.length) select(ms[0].dataset.id, false);
  if (!ms.length) composer.focus();
})();
