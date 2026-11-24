// Working against an existing codebase: needs the server started with --project pointing at tests/sample_project
// and the agent bridge test (tests/agent_bridge.py) run first, so the dialog holds a cell added by the agent.
const { chromium } = require('playwright');
const fs = require('fs');
const out = process.argv[2], proj = process.argv[3];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  p.on('dialog', d => d.accept());
  const idle = () => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 60000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); };
  const { log, exp, done } = require('./_check')();
  const last = sel => p.$eval('#msgs > .msg:last-child ' + sel, e => e.innerText.replace(/\s+/g, ' ').slice(0, 200));
  const clickWord = async (scope, word, mods = ['Control']) => {
    const box = await p.evaluate(([scope, word]) => {
      const root = [...document.querySelectorAll(scope)].pop();
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n; (n = w.nextNode());) { const i = n.data.indexOf(word); if (i >= 0) { const r = document.createRange(); r.setStart(n, i + 1); r.setEnd(n, i + word.length - 1); const q = r.getBoundingClientRect(); return { x: q.x + q.width / 2, y: q.y + q.height / 2 }; } }
    }, [scope, word]);
    for (const m of mods) await p.keyboard.down(m);
    await p.mouse.click(box.x, box.y);
    for (const m of mods) await p.keyboard.up(m);
  };
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg');

  // 1. cells the agent added are marked
  log('1 agent-marked cells', await p.$$eval('.msg.by-agent', els => els.map(e => e.dataset.type + ':' + e.querySelector('.f-by').innerText)));
  exp('1 agent-marked cells', v => v.length === 2 && v.every(x => /added by agent/.test(x)));

  // 2. go to definition: from a cell, then follow a name inside the shown source
  await p.$eval('.msg.by-agent.t-code', e => e.scrollIntoView());
  await type('code', 'from acme.orders import Order, order_total\ntotal = order_total(Order([(5.0, 2)]))\ntotal'); await p.waitForTimeout(500); await idle();
  log('2 ran against project', await last('.mout'));
  exp('2 ran against project', '12.0');
  await clickWord('#msgs > .msg:last-child .min pre', 'order_total'); await p.waitForSelector('#defn:not([hidden])');
  log('2 panel title', await p.$eval('#dtitle', e => e.innerText));
  exp('2 panel title', 'order_total(order: acme.orders.Order) -> float');
  log('2 panel file', (await p.$eval('#dmeta .path', e => e.innerText)).replace(/\/tmp\/\S+\/tests/, '…/tests').replace(/\/tmp\/\S+\/proj/, '…/proj'));
  exp('2 panel file', /function in acme\.orders .*acme\/orders\.py:11/);
  log('2 panel source', (await p.$eval('#dbody', e => e.innerText)).replace(/\s+/g, ' ').slice(0, 110));
  exp('2 panel source', /def order_total\(order: Order\) -> float:/);
  await clickWord('#dbody pre', 'with_tax'); await p.waitForFunction(() => /with_tax/.test(document.querySelector('#dtitle').innerText));
  log('2 followed into', [await p.$eval('#dtitle', e => e.innerText), (await p.$eval('#dmeta .path', e => e.innerText)).split('/').pop()]);
  exp('2 followed into', v => v[0] === 'with_tax(amount: float) -> float' && v[1] === 'pricing.py:4');
  await p.screenshot({ path: out + '/07-definition.png' });
  await p.click('#dcode'); await p.waitForTimeout(600);
  log('2 brought in as a linked cell', await p.$eval('.msg.sel .min', e => e.innerText.replace(/\/tmp\/\S+\/(proj|tests)/, '…').split('\n').slice(0, 4).join(' | ')));
  exp('2 brought in as a linked cell', /^def with_tax\(amount: float\) -> float:/);
  await p.click('#dback'); await p.waitForFunction(() => /order_total/.test(document.querySelector('#dtitle').innerText)); await p.click('#dclose');
  await p.focus('#msgs'); await p.keyboard.press('x'); await p.waitForTimeout(400);

  // 3. project setup: code runs at kernel start, notes reach the AI, autoreload picks up file edits
  await p.goto('http://127.0.0.1:5001/'); await p.click('.setupform button'); await p.waitForURL(/SETUP/); await p.waitForSelector('.msg');
  await type('code', 'SETUP_RAN = "yes from setup"'); await p.waitForTimeout(400);
  await type('note', 'Project rule: money is always rounded to 2 decimal places.'); await p.waitForTimeout(400);
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg'); await p.focus('#msgs'); await p.keyboard.press('Shift+R'); await p.waitForTimeout(1500);
  await type('code', 'from acme.pricing import with_tax\nSETUP_RAN, with_tax(100)'); await p.waitForTimeout(500); await idle();
  log('3 setup ran in new kernel', await last('.mout'));
  exp('3 setup ran in new kernel', "('yes from setup', 120.0)");
  log('3 no setup error banner', await p.$eval('#banner', e => e.hidden));
  exp('3 no setup error banner', true);
  const f = proj + '/acme/pricing.py', orig = fs.readFileSync(f, 'utf8');
  fs.writeFileSync(f, orig.replace('TAX = 0.2', 'TAX = 0.5')); await p.waitForTimeout(1200);
  await type('code', 'with_tax(100)'); await p.waitForTimeout(500); await idle();
  log('3 autoreload after file edit', await last('.mout'));
  exp('3 autoreload after file edit', '150.0');
  fs.writeFileSync(f, orig);
  // a broken setup is reported, not swallowed
  await p.goto('http://127.0.0.1:5001/d/SETUP'); await p.waitForSelector('.msg'); await type('code', 'import module_that_does_not_exist'); await p.waitForTimeout(600);
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg'); await p.focus('#msgs'); await p.keyboard.press('Shift+R'); await p.waitForTimeout(1200);
  await type('code', 'SETUP_RAN'); await p.waitForTimeout(500); await idle();
  log('3 broken setup banner', (await p.$eval('#banner', e => e.hidden ? 'HIDDEN' : e.innerText)).slice(0, 120));
  exp('3 broken setup banner', /SETUP failed in code message \d+: ModuleNotFoundError/);
  log('3 rest of setup still ran', await last('.mout'));
  exp('3 rest of setup still ran', /yes from setup/);

  // 4. modes: basic and grill; the grilling skill and the project notes reach the model
  log('4 modes', await p.$$eval('#mode option', o => o.map(x => x.value)));
  exp('4 modes', ['basic', 'grill']);
  await p.selectOption('#mode', 'grill'); await p.waitForTimeout(300);
  await type('prompt', 'I plan to change with_tax to take a rate argument.'); await p.waitForTimeout(1500); await idle();
  const seen = await (await fetch('http://127.0.0.1:8765/seen')).json(); const sys = JSON.stringify(seen.messages[0]);
  log('4 system prompt', { grill: /Mode: GRILL/.test(sys), skill: /design tree/.test(sys) && /frontier/.test(sys), projectNotes: /money is always rounded/.test(sys) });
  exp('4 system prompt', v => v.grill && v.skill && v.projectNotes);
  await p.selectOption('#mode', 'basic'); await p.waitForTimeout(300);
  await type('prompt', 'again'); await p.waitForTimeout(1500); await idle();
  const sys2 = JSON.stringify((await (await fetch('http://127.0.0.1:8765/seen')).json()).messages[0]);
  log('4 basic has no skill', !/design tree/.test(sys2) && /money is always rounded/.test(sys2));
  exp('4 basic has no skill', true);
  done(errs);
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 700)); process.exit(1); });
