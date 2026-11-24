// Codebase round trip: bring functions in as linked cells, run them inside their module, see what changed, write back.
// Needs the server started with --project <copy of tests/sample_project>; pass that folder as the first argument.
const { chromium } = require('playwright');
const fs = require('fs');
const proj = process.argv[2], shots = process.argv[3];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  p.on('dialog', d => d.accept());
  const idle = () => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 90000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(600); await idle(); };
  const log = (k, v) => console.log(k, '=>', typeof v === 'string' ? v : JSON.stringify(v));
  const read = f => fs.readFileSync(proj + '/' + f, 'utf8');
  const must = (ok, what) => { if (!ok) throw new Error('ASSERTION FAILED: ' + what); };
  const wordBox = (scope, word) => p.evaluate(([scope, word]) => {
    const root = [...document.querySelectorAll(scope)].pop(); root.scrollIntoView({ block: 'center' });
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) { const i = n.data.indexOf(word); if (i >= 0) { const r = document.createRange(); r.setStart(n, i + 1); r.setEnd(n, i + word.length - 1); const q = r.getBoundingClientRect(); return { x: q.x + q.width / 2, y: q.y + q.height / 2 }; } }
  }, [scope, word]);
  const ctrlClick = async (scope, word) => { const q = await wordBox(scope, word); await p.keyboard.down('Control'); await p.mouse.click(q.x, q.y); await p.keyboard.up('Control'); };
  const linked = () => p.$$eval('#msgs > .msg.is-linked', els => els.map(e => e.querySelector('.f-src').innerText + (e.className.includes('by-ai') ? ' [AI]' : '')));
  const cellOf = name => `#msgs > .msg.is-linked:has(.f-src:text-matches("${name}"))`;
  const lastOut = () => p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.replace(/\s+/g, ' ').trim().slice(0, 150));
  const editCell = async (sel, from, to) => { await p.click(sel + ' .mhead'); await p.keyboard.press('Enter'); await p.waitForSelector(sel + ' .editor .CodeMirror');
    await p.$eval(sel + ' .editor .CodeMirror', (e, [from, to]) => e.CodeMirror.setValue(e.CodeMirror.getValue().replace(from, to)), [from, to]); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(700); await idle(); };

  await p.goto('http://127.0.0.1:5001/'); await p.fill('input[name=name]', 'flow'); await p.click('.newdlg button'); await p.waitForURL(/flow/);
  // autoreload on, as a project SETUP normally has it: running cells in their module has to work alongside it
  await type('code', '%load_ext autoreload\n%autoreload 2');
  await type('code', 'from acme.orders import Order, order_total\no = Order([(100.0, 1)])\norder_total(o)');
  log('0 baseline', await lastOut()); must((await lastOut()) === '120.0', 'baseline order_total is 120.0');

  // bring in order_total from the definition panel; then follow a name that only its module knows
  await ctrlClick('#msgs > .msg:last-child .min pre', 'order_total'); await p.waitForSelector('#defn:not([hidden])');
  log('1 panel', [await p.$eval('#dcode', e => e.innerText), (await p.$eval('#dmeta a', e => e.href)).replace(/(vscode:\/\/[a-z-]+).*?(\/acme.*)/, '$1…$2')]);
  await p.click('#dcode'); await p.waitForSelector('.msg.is-linked'); await p.click('#dclose');
  log('1 linked cell', await linked());
  const q = await wordBox('.msg.is-linked .min pre', 'with_tax'); await p.mouse.click(q.x, q.y, { button: 'right' }); await p.waitForSelector('#ctxmenu:not([hidden])');
  log('2 right-click menu', await p.$eval('#ctxmenu', e => e.innerText)); await p.click('#ctxmenu button'); await p.waitForFunction(() => /with_tax/.test(document.querySelector('#dtitle').innerText));
  log('2 resolved inside its module', await p.$eval('#dmeta .path', e => e.innerText.replace(/\/\S+\/acme/, '…/acme')));
  await p.click('#dcode'); await p.waitForFunction(() => document.querySelectorAll('.msg.is-linked').length === 2); await p.click('#dclose');
  log('2 linked cells', await linked());

  // modify to understand: edit, run, the whole package uses it, the file is untouched
  const before = read('acme/pricing.py');
  await editCell(cellOf('with_tax'), 'return round(amount * (1 + TAX), 2)', 'print("with_tax called with", amount)\n    return round(amount * (1 + TAX), 2) + 1000');
  log('3 after edit', [await linked(), await p.$eval(cellOf('with_tax') + ' .mout', e => e.innerText.slice(0, 70))]);
  await type('code', 'order_total(o)'); log('3 caller in another file uses my version', await lastOut());
  must(/with_tax called with 100.0 1120.0/.test(await lastOut()), 'a caller in another file uses the edited function');
  log('3 file untouched', read('acme/pricing.py') === before); must(read('acme/pricing.py') === before, 'running a linked cell does not touch the file');

  // Changes: review and write back
  await p.click('#chgbtn'); await p.waitForSelector('#modal:not([hidden]) .chglist');
  log('4 changes panel', await p.$eval('.chglist', e => e.innerText.replace(/\s+/g, ' ').slice(0, 260)));
  if (shots) await p.screenshot({ path: shots + '/09-changes.png' });
  await p.click('#modal button.primary'); await p.waitForFunction(() => /match their files/.test(document.querySelector('#mbox').innerText)); await p.click('#modal .mbtns button:last-child');
  log('4 written', [/\+ 1000/.test(read('acme/pricing.py')), await linked()]); must(/\+ 1000/.test(read('acme/pricing.py')) && (await linked()).every(l => /in sync/.test(l)), 'change written and everything in sync');

  // changed on disk, then conflict
  fs.writeFileSync(proj + '/acme/pricing.py', read('acme/pricing.py').replace('+ 1000', '+ 2000')); await p.reload(); await p.waitForSelector('.msg.is-linked');
  log('5 someone else edits the file', await linked()); must((await linked()).some(l => /with_tax · changed on disk/.test(l)), 'a file edited elsewhere shows as changed on disk');
  await editCell(cellOf('with_tax'), '+ 1000', '+ 3000'); log('6 I edit too', await linked()); must((await linked()).some(l => /with_tax · conflict/.test(l)), 'both sides changed shows as a conflict');
  await p.click(cellOf('with_tax') + ' .mhead'); await p.click(cellOf('with_tax') + ' [data-act=diff]'); await p.waitForSelector('#modal:not([hidden]) pre.diff');
  log('6 conflict dialog', [await p.$eval('#mbox .fine', e => e.innerText.slice(0, 60)), await p.$$eval('#mbox .mbtns button', bs => bs.map(x => x.innerText))]);
  await p.click('#mbox .mbtns button:nth-child(2)'); await p.waitForTimeout(900); await idle();
  log('7 reverted to the file', [await linked(), /\+ 2000/.test(await p.$eval(cellOf('with_tax') + ' .min', e => e.innerText))]);
  await type('code', 'order_total(o)'); log('7 memory matches the file again', await lastOut()); must(/2120.0/.test(await lastOut()), 'after revert the loaded code is the file version');

  // new code: say where it goes, then write it
  await type('code', 'def discount(amount: float) -> float:\n    "10% off."\n    return round(amount * 0.9, 2)');
  await p.click('#msgs > .msg:last-child .mhead'); await p.click('#msgs > .msg:last-child [data-act=tofile]'); await p.waitForSelector('#modal:not([hidden]) select');
  await p.fill('#mbox input[list]', 'acme/pricing.py'); await p.$eval('#mbox input[list]', e => e.dispatchEvent(new Event('change'))); await p.waitForTimeout(400);
  log('8 destination choices', await p.$$eval('#mbox select option', o => o.map(x => x.textContent.trim())));
  await p.selectOption('#mbox select', 'with_tax'); await p.click('#mbox button.primary'); await p.waitForTimeout(500);
  log('8 destination recorded, nothing written', [(await linked()).pop(), /discount/.test(read('acme/pricing.py'))]);
  await p.click('#msgs > .msg:last-child [data-act=apply]'); await p.waitForSelector('#modal:not([hidden]) pre.diff'); await p.click('#mbox button.primary'); await p.waitForTimeout(600);
  log('8 written', [(await linked()).pop(), read('acme/pricing.py').split('\n').filter(l => /^def |^TAX/.test(l))]);
  await type('code', 'def count(self):\n    return len(self.items)');
  await p.click('#msgs > .msg:last-child .mhead'); await p.click('#msgs > .msg:last-child [data-act=tofile]'); await p.waitForSelector('#modal:not([hidden]) select');
  await p.fill('#mbox input[list]', 'acme/orders.py'); await p.$eval('#mbox input[list]', e => e.dispatchEvent(new Event('change'))); await p.waitForTimeout(400);
  await p.selectOption('#mbox select', 'Order.subtotal'); await p.click('#mbox button.primary'); await p.waitForTimeout(500);
  await p.click('#msgs > .msg:last-child .mhead'); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(600); await idle();
  await type('code', 'o.count()'); log('9 new method works before it is in the file', await lastOut()); must((await lastOut()) === '1', 'a new method runs before it is written');
  await p.click('#chgbtn'); await p.waitForSelector('#modal:not([hidden]) .chglist'); await p.click('#modal button.primary'); await p.waitForFunction(() => /match their files/.test(document.querySelector('#mbox').innerText)); await p.click('#modal .mbtns button:last-child');
  log('9 written inside the class', read('acme/orders.py').split('\n').filter(l => /def |^class /.test(l)).map(l => l.replace(/\(.*/, '')));
  require('child_process').execSync(`python -c "import ast,sys; [ast.parse(open(f).read()) for f in sys.argv[1:]]" ${proj}/acme/pricing.py ${proj}/acme/orders.py`);
  log('9 both files still parse', true);
  must(JSON.stringify(read('acme/orders.py').split('\n').filter(l => /def |^class /.test(l)).map(l => l.replace(/\(.*/, '').trim())) === JSON.stringify(['class Order:', 'def __init__', 'def subtotal', 'def count', 'def order_total']), 'new method written inside the class');

  // an import written at the top of a cell goes to the file's import block, not next to the function
  await p.click(cellOf('discount') + ' .mhead'); await p.keyboard.press('Enter'); await p.waitForSelector(cellOf('discount') + ' .editor .CodeMirror');
  await p.$eval(cellOf('discount') + ' .editor .CodeMirror', e => e.CodeMirror.setValue('import math\n\n' + e.CodeMirror.getValue().replace('round(amount * 0.9, 2)', 'math.floor(amount * 0.9)')));
  await p.keyboard.press('Control+Enter'); await p.waitForTimeout(700); await idle();
  await type('code', 'from acme.pricing import discount\ndiscount(101)'); log('11 import in the cell works when run', await lastOut()); must((await lastOut()) === '90', 'a function whose cell brings its own import runs');
  await p.click('#chgbtn'); await p.waitForSelector('#modal:not([hidden]) .chglist');
  log('11 diff says where the import goes', (await p.$eval('.chglist pre.diff', e => e.innerText)).split('\n')[0]);
  await p.click('#modal button.primary'); await p.waitForFunction(() => /match their files/.test(document.querySelector('#mbox').innerText)); await p.click('#modal .mbtns button:last-child');
  const pf = read('acme/pricing.py').split('\n');
  log('11 import at top of file, not by the function', [pf.indexOf('import math') < pf.findIndex(l => l.startsWith('TAX')), pf[pf.findIndex(l => l.startsWith('def discount')) - 1] === '']);
  must(pf.indexOf('import math') >= 0 && pf.indexOf('import math') < pf.findIndex(l => l.startsWith('TAX')) && pf.filter(l => l === 'import math').length === 1, 'import moved to the top of the file, once');
  log('11 cell now holds just the function, in sync', [(await p.$eval(cellOf('discount') + ' .min', e => e.innerText)).split('\n')[0], (await linked()).filter(l => /discount/.test(l))]);

  // the notebook's AI brings code in by name; Polya does the copying
  await p.check('#dtools');
  await type('prompt', 'show me [[call add_source {"symbol": "Order.subtotal", "file": "acme/orders.py"}]]');
  log('10 AI used add_source', [(await linked()).pop(), (await p.$eval('#msgs > .msg:last-child .min', e => e.innerText)).replace(/\s+/g, ' ').slice(0, 60)]);
  await type('prompt', 'and this [[call add_source {"symbol": "nope", "file": "acme/orders.py"}]]');
  log('10 unknown symbol', (await p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.replace(/\s+/g, ' '))).match(/returned: (.{0,110})/)[1]);
  must(errs.length === 0, 'no browser console errors');
  console.log('ERRORS', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 900)); process.exit(1); });
