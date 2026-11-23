// Run all / above / below run code only: prompts are never re-sent, unreviewed AI-written cells are skipped.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  const idle = () => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 90000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(500); await idle(); };
  const log = (k, v) => console.log(k, '=>', typeof v === 'string' ? v : JSON.stringify(v));
  const llmCalls = async () => (await (await fetch('http://127.0.0.1:8765/count')).json()).count;
  const outs = () => p.$$eval('#msgs > .msg.t-code', els => els.map(e => e.querySelector('.mout').innerText.trim()));
  const replies = () => p.$$eval('#msgs > .msg.t-prompt .mout', els => els.map(e => e.innerText.replace(/\s+/g, ' ').trim()));
  const selectNth = async n => { await p.click(`#msgs > .msg:nth-child(${n}) .mhead`); };
  const bulk = async key => { await p.focus('#msgs'); await p.keyboard.press(key); await p.waitForTimeout(700); await idle(); };
  await p.goto('http://127.0.0.1:5001/'); await p.fill('input[name=name]', 'bulk'); await p.click('.newdlg button'); await p.waitForURL(/bulk/);
  // layout: 1 code, 2 prompt, 3 code, 4 prompt (edited reply), 5 code, then an AI-written cell
  await type('code', 'import itertools\nif "tick" not in globals(): tick = itertools.count(1)\nprint("A", next(tick))');
  await type('prompt', 'first question');
  await type('code', 'print("B", next(tick))');
  await type('prompt', 'second question');
  await type('code', 'print("C", next(tick))');
  await selectNth(4); await p.keyboard.press('n'); await p.waitForSelector('.editor .CodeMirror');
  await p.keyboard.press('Control+a'); await p.keyboard.insertText('MY EDITED REPLY'); await p.keyboard.press('Escape'); await p.waitForTimeout(500);
  await p.check('#dtools');
  await type('prompt', 'add a cell [[call add_msg {"content": "print(\\"AI CELL RAN\\")", "msg_type": "code", "run": true}]]');
  log('0 start outputs', await outs());
  const before = { calls: await llmCalls(), replies: await replies() };

  await p.$$eval('.toast', els => els.forEach(e => e.remove()));
  await bulk('r');
  log('1 run all: code reran', await outs());
  log('1 run all: toast', await p.$eval('.toast', e => e.innerText).catch(() => ''));
  log('1 run all: no LLM calls, replies untouched', [(await llmCalls()) - before.calls, JSON.stringify(await replies()) === JSON.stringify(before.replies), (await replies())[1]]);

  await selectNth(3); await bulk('Shift+A');
  log('2 above message 3: only A reran', await outs());
  await selectNth(3); await bulk('Shift+B');
  log('3 from message 3 down: B and C reran, A did not', await outs());
  log('3 still no LLM calls', (await llmCalls()) - before.calls);

  // once I run the AI's cell myself it is mine, and bulk runs include it
  await p.click('#msgs > .msg.by-ai .mhead'); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(500); await idle();
  log('4 after I run the AI cell', [await p.$$eval('.msg.by-ai', e => e.length), (await outs()).pop()]);
  await p.$$eval('.toast', els => els.forEach(e => e.remove()));
  await bulk('r');
  log('4 run all now includes it', await p.$eval('.toast', e => e.innerText).catch(() => ''));
  log('5 total LLM calls caused by bulk runs', (await llmCalls()) - before.calls);
  console.log('ERRORS', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 700)); process.exit(1); });
