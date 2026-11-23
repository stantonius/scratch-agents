const { chromium } = require('playwright');
const out = process.argv[2];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  const idle = () => p.waitForFunction(() => document.querySelector('#kstat').classList.contains('idle') && !document.querySelector('.is-running'), null, { timeout: 40000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); };
  const log = (k, v) => console.log(k, '=>', typeof v === 'string' ? v : JSON.stringify(v));
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg');

  // 1. send the first prompt, then extract its code block and run it
  const p1 = await p.$$eval('.t-prompt', els => els[0].dataset.id);
  await p.click(`#m-${p1} .mhead`); await p.keyboard.press('Control+Enter');
  await p.waitForFunction(id => /Run it and tell me/.test(document.querySelector(`#m-${id} .mout`).innerText), p1, { timeout: 30000 }); await idle();
  log('1 reply', await p.$eval(`#m-${p1} .mout`, e => e.innerText.slice(0, 120)));
  await p.keyboard.press('w'); await p.waitForTimeout(600);
  const sel = await p.$eval('.msg.sel', e => [e.dataset.type, e.querySelector('.min').innerText]); log('1 extracted', sel);
  await p.keyboard.press('Control+Enter'); await p.waitForTimeout(300); await idle();
  log('1 extracted output', await p.$eval('.msg.sel .mout', e => e.innerText));
  log('1 composer type after prompt', await p.$eval('#composer', e => e.dataset.type));

  // 2. a tool defined in the kernel, plus a $ variable
  await type('prompt', 'Compute it [[call total_distance {"a": [1,2,3], "b": [3,4,9]}]] using &`total_distance`, and note $`len(l1)`');
  await p.waitForFunction(() => /returned: 10/.test(document.querySelector('#msgs').lastElementChild.innerText), null, { timeout: 30000 }); await idle();
  log('2 tool reply', await p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.replace(/\s+/g, ' ').slice(0, 200)));
  const seen = await (await fetch('http://127.0.0.1:8765/seen')).json();
  log('2 tools offered', seen.tools.map(t => t.function.name));
  log('2 has variables block', (seen.messages.map(m => typeof m.content === 'string' ? m.content : JSON.stringify(m.content)).join(' ').match(/<variable name=.{0,60}variable>/) || ['MISSING'])[0]);
  log('2 system prompt sent', /dialog-based notebook/.test(JSON.stringify(seen.messages[0])));
  await p.screenshot({ path: out + '/03-tool.png' });

  // 3. AI injects a code cell and runs it
  await p.check('#dtools');
  await type('prompt', 'Please add it [[call add_msg {"content": "print(\'injected by AI\', 6*7)", "msg_type": "code", "run": true}]]');
  await p.waitForFunction(() => /injected by AI 42/.test(document.querySelector('#msgs').innerText), null, { timeout: 30000 }); await idle();
  const tail = await p.$$eval('#msgs > .msg', els => els.slice(-2).map(e => [e.dataset.type, e.querySelector('.min').innerText.slice(0, 50), e.querySelector('.mout').innerText.replace(/\s+/g, ' ').slice(0, 130)])); log('3 tail', tail);

  // 4. the same tool, called by the human from code
  await type('code', "add_msg('hello from code', 'note')"); await p.waitForTimeout(500); await idle();
  log('4 last two', await p.$$eval('#msgs > .msg', els => els.slice(-2).map(e => [e.dataset.type, e.innerText.replace(/\s+/g, ' ').slice(0, 90)])));

  // 5. dialog engineering: hide, pin, edit the AI's reply
  await p.click(`#m-${p1} .mhead`); await p.keyboard.press('h'); await p.keyboard.press('p'); await p.waitForTimeout(400);
  log('5 classes', await p.$eval(`#m-${p1}`, e => e.className));
  await p.keyboard.press('h'); await p.keyboard.press('n'); await p.waitForSelector(`#m-${p1} .editor .CodeMirror`);
  await p.keyboard.press('Control+a'); await p.keyboard.insertText('Edited reply: think about `o.split()[1]`.'); await p.keyboard.press('Escape'); await p.waitForTimeout(500);
  log('5 edited reply', await p.$eval(`#m-${p1} .mout`, e => e.innerText));
  await type('prompt', 'check context'); await p.waitForTimeout(1500); await idle();
  const seen2 = await (await fetch('http://127.0.0.1:8765/seen')).json();
  log('5 edited reply sent to model', /Edited reply: think about/.test(JSON.stringify(seen2.messages)));

  // 6. stop a long-running cell
  await type('code', 'import time\nfor i in range(100):\n    print(i); time.sleep(0.3)'); await p.waitForTimeout(1500);
  log('6 streaming', await p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.replace(/\s+/g, ' ').slice(0, 30)));
  await p.focus('#msgs'); await p.keyboard.press('Shift+S'); await idle();
  log('6 after stop', await p.$eval('#msgs > .msg:last-child .mout', e => /KeyboardInterrupt/.test(e.innerText)));

  // 7. sidebar + help
  await p.click('#sidetoggle'); await p.waitForTimeout(800);
  log('7 vars', await p.$eval('#vars', e => e.innerText.replace(/\s+/g, ' ').slice(0, 120)));
  log('7 funcs', await p.$eval('#funcs', e => e.innerText.replace(/\s+/g, ' ').slice(0, 160)));
  await p.screenshot({ path: out + '/04-end.png' });
  await p.focus('#msgs'); await p.keyboard.press('?'); await p.waitForTimeout(200); await p.screenshot({ path: out + '/05-help.png' });
  console.log('ERRORS', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 600)); process.exit(1); });
