const { chromium } = require('playwright');
const out = process.argv[2];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  const idle = () => p.waitForFunction(() => document.querySelector('#kstat').classList.contains('idle') && !document.querySelector('.is-running'), null, { timeout: 40000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); };
  const { log, exp, done } = require('./_check')();
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg');

  // 1. send the first prompt, then extract its code block and run it
  const p1 = await p.$$eval('.t-prompt', els => els[0].dataset.id);
  await p.click(`#m-${p1} .mhead`); await p.keyboard.press('Control+Enter');
  await p.waitForFunction(id => /Run it and tell me/.test(document.querySelector(`#m-${id} .mout`).innerText), p1, { timeout: 30000 }); await idle();
  log('1 reply', await p.$eval(`#m-${p1} .mout`, e => e.innerText.slice(0, 120)));
  exp('1 reply', /Run it and tell me/);
  await p.keyboard.press('w'); await p.waitForTimeout(600);
  const sel = await p.$eval('.msg.sel', e => [e.dataset.type, e.querySelector('.min').innerText]); log('1 extracted', sel);
  exp('1 extracted', v => v[0] === 'code' && v[1].trim() === 'sorted(l1)');
  await p.keyboard.press('Control+Enter'); await p.waitForTimeout(300); await idle();
  log('1 extracted output', await p.$eval('.msg.sel .mout', e => e.innerText));
  exp('1 extracted output', /^\[1, 2, 3, 3, 3, 4\]\s*$/);
  log('1 composer type after prompt', await p.$eval('#composer', e => e.dataset.type));
  exp('1 composer type after prompt', 'code');

  // 2. a tool defined in the kernel, plus a $ variable
  await type('prompt', 'Compute it [[call total_distance {"a": [1,2,3], "b": [3,4,9]}]] using &`total_distance`, and note $`len(l1)`');
  await p.waitForFunction(() => /returned: 10/.test(document.querySelector('#msgs').lastElementChild.innerText), null, { timeout: 30000 }); await idle();
  log('2 tool reply', await p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.replace(/\s+/g, ' ').slice(0, 200)));
  exp('2 tool reply', /Tool total_distance returned: 10/);
  const seen = await (await fetch('http://127.0.0.1:8765/seen')).json();
  log('2 tools offered', seen.tools.map(t => t.function.name));
  exp('2 tools offered', ['python', 'bash', 'total_distance', 'search_code', 'outline', 'read_lines', 'source_of']);   // the sandboxed tools are on by default
  log('2 has variables block', (seen.messages.map(m => typeof m.content === 'string' ? m.content : JSON.stringify(m.content)).join(' ').match(/<variable name=.{0,60}variable>/) || ['MISSING'])[0]);
  exp('2 has variables block', /<variable name="len\(l1\)">6<\/variable>/);
  log('2 system prompt sent', /dialog-based notebook/.test(JSON.stringify(seen.messages[0])));
  exp('2 system prompt sent', true);
  await p.screenshot({ path: out + '/03-tool.png' });

  // 3. AI adds a code cell. Without "AI can run code" it is NOT run: the human runs it.
  await p.uncheck('#ctools');   // with the AI's code tools off, what it writes waits for you
  await p.check('#dtools');
  await type('prompt', 'Please add it [[call add_msg {"content": "print(\'injected by AI\', 6*7)", "msg_type": "code", "run": true}]]');
  await p.waitForFunction(() => /NOT run/.test(document.querySelector('#msgs').innerText), null, { timeout: 30000 }); await idle();
  const tail = await p.$$eval('#msgs > .msg', els => els.slice(-1).map(e => [e.dataset.type, e.className.includes('by-ai'), e.querySelector('.min').innerText.slice(0, 50), e.querySelector('.mout').innerText.trim()])); log('3 AI cell added, not run', tail);
  exp('3 AI cell added, not run', v => v.length === 1 && v[0][0] === 'code' && v[0][1] === true && v[0][3] === '');
  await p.click('#msgs > .msg:last-child .mhead'); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(400); await idle();
  log('3 after the human runs it', await p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.trim()));
  exp('3 after the human runs it', 'injected by AI 42');

  // 4. the same tool, called by the human from code
  await type('code', "add_msg('hello from code', 'note')"); await p.waitForTimeout(500); await idle();
  log('4 last two', await p.$$eval('#msgs > .msg', els => els.slice(-2).map(e => [e.dataset.type, e.innerText.replace(/\s+/g, ' ').slice(0, 90)])));
  exp('4 last two', v => v[0][0] === 'code' && v[1][0] === 'note' && /hello from code/.test(v[1][1]));

  // 5. dialog engineering: hide, pin, edit the AI's reply
  await p.click(`#m-${p1} .mhead`); await p.keyboard.press('h'); await p.keyboard.press('p'); await p.waitForTimeout(400);
  log('5 classes', await p.$eval(`#m-${p1}`, e => e.className));
  exp('5 classes', (v, s) => /is-hidden/.test(s) && /is-pinned/.test(s));
  await p.keyboard.press('h'); await p.keyboard.press('n'); await p.waitForSelector(`#m-${p1} .editor .CodeMirror`);
  await p.keyboard.press('Control+a'); await p.keyboard.insertText('Edited reply: think about `o.split()[1]`.'); await p.keyboard.press('Escape'); await p.waitForTimeout(500);
  log('5 edited reply', await p.$eval(`#m-${p1} .mout`, e => e.innerText));
  exp('5 edited reply', /Edited reply: think about o\.split\(\)\[1\]\./);
  await type('prompt', 'check context'); await p.waitForTimeout(1500); await idle();
  const seen2 = await (await fetch('http://127.0.0.1:8765/seen')).json();
  log('5 edited reply sent to model', /Edited reply: think about/.test(JSON.stringify(seen2.messages)));
  exp('5 edited reply sent to model', true);

  // 6. stop a long-running cell
  await type('code', 'import time\nfor i in range(100):\n    print(i); time.sleep(0.3)'); await p.waitForTimeout(1500);
  log('6 streaming', await p.$eval('#msgs > .msg:last-child .mout', e => e.innerText.replace(/\s+/g, ' ').slice(0, 30)));
  exp('6 streaming', /^0 1 2/);
  await p.focus('#msgs'); await p.keyboard.press('Shift+S'); await idle();
  log('6 after stop', await p.$eval('#msgs > .msg:last-child .mout', e => /KeyboardInterrupt/.test(e.innerText)));
  exp('6 after stop', true);

  // 7. sidebar + help
  await p.click('#sidetoggle'); await p.waitForTimeout(800);
  log('7 vars', await p.$eval('#vars', e => e.innerText.replace(/\s+/g, ' ').slice(0, 120)));
  exp('7 vars', /l1 \[3, 4, 2, 1, 3, 3\]/);
  log('7 funcs', await p.$eval('#funcs', e => e.innerText.replace(/\s+/g, ' ').slice(0, 160)));
  exp('7 funcs', /total_distance \(a: list\[int\], b: list\[int\]\) -> int/);
  await p.screenshot({ path: out + '/04-end.png' });
  await p.focus('#msgs'); await p.keyboard.press('?'); await p.waitForTimeout(200); await p.screenshot({ path: out + '/05-help.png' });
  done(errs);
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 600)); process.exit(1); });
