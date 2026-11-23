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
        F12: cm => showDef(nameAt(cm.getValue(), cm.indexFromPos(cm.getCursor()))),
      }, keys),
    });
    cm.on('mousedown', (cm, e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      showDef(nameAt(cm.getValue(), cm.indexFromPos(cm.coordsChar({left: e.clientX, top: e.clientY}))));
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
    const hint = document.createElement('div'); hint.textContent = 'Ctrl+click a name in this source to follow it further.'; meta.append(hint);
    $('#dbody').innerHTML = d.html || '';
    if (!d.html && d.doc) { const p = document.createElement('pre'); p.textContent = d.doc; $('#dbody').append(p); }
    $('#dcode').disabled = $('#dnote').disabled = !d.source;
    $('#dbody').scrollTop = 0;
  }
  function closeDef() { $('#defn').hidden = true; defStack = []; defCur = null; }
  async function insertDef(asNote) {
    const d = defCur;
    if (!d || !d.source) return;
    const where = `${d.file || 'unknown file'}:${d.line}`;
    const content = asNote
      ? `Definition of \`${d.name}\` (${where}):\n\n\`\`\`python\n${d.source.replace(/\n$/, '')}\n\`\`\``
      : `# Copy of ${d.module ? d.module + '.' : ''}${d.qualname} from ${where}\n# Running this redefines the name in this kernel only; the file is not changed.\n${d.source.replace(/\n$/, '')}`;
    const body = {op: 'add', type: asNote ? 'note' : 'code', content};
    if (selected) body.after = selected;
    const r = await post(body);
    if (r.id) { wantSelect = r.id; if (byId(r.id)) select(r.id); toast(asNote ? 'Added as a note' : 'Added as a code message (not run)'); }
  }

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
      return showDef(nameAtPoint(e.target.closest('pre'), e.clientX, e.clientY));
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
      r: () => post({op: 'runall'}), R: () => restart(), S: () => post({op: 'stop'}),
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

  function restart() { if (confirm('Restart the kernel? All variables will be lost.')) post({op: 'restart'}); }

  document.querySelectorAll('.ctype').forEach(b => b.onclick = () => { setCType(b.dataset.type); composer.focus(); });
  $('#csend').onclick = () => submit(false);
  $('#runall').onclick = () => post({op: 'runall'});
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
