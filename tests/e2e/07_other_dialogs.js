// The notebook's AI (and your own code) can read and edit other dialogs in the folder, but not run code there.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1360, height: 900 } });
  const errs = []; const watch = p => { p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message)); };
  const idle = p => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 90000 });
  const type = async (p, kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(600); await idle(p); };
  const { log, exp, done } = require('./_check')();
  const mk = async name => { const p = await ctx.newPage(); watch(p); await p.goto('http://127.0.0.1:5001/'); await p.fill('input[name=name]', name); await p.click('.newdlg button'); await p.waitForURL(new RegExp(name)); return p; };
  const cells = p => p.$$eval('#msgs > .msg', els => els.map(e => `${e.dataset.type}${e.className.includes('by-ai') ? '[AI]' : ''}:${e.querySelector('.min').innerText.replace(/\s+/g, ' ').slice(0, 34)}`));

  const beta = await mk('beta');
  await type(beta, 'note', 'Beta notes: findings so far');
  await type(beta, 'code', 'beta_value = 1\nbeta_value');
  const betaCode = await beta.$eval('#msgs > .msg.t-code', e => e.dataset.id);
  const alpha = await mk('alpha');
  await alpha.check('#dtools');
  const ask = async (tool, args) => {
    const n = await alpha.$$eval('#msgs > .msg', e => e.length);
    await type(alpha, 'prompt', `go [[call ${tool} ${JSON.stringify(args)}]]`);
    await alpha.waitForFunction(n => document.querySelectorAll('#msgs > .msg').length > n, n); await alpha.waitForTimeout(300); await idle(alpha);
    const t = await alpha.$eval(`#msgs > .msg:nth-child(${n + 1}) .mout`, e => e.innerText.replace(/\s+/g, ' ')); const i = t.indexOf('returned:');
    return t.slice(i + 10, i + 190);
  };
  log('1 list_dialogs', await ask('list_dialogs', {}));
  exp('1 list_dialogs', /alpha \(this dialog\).* beta/);
  log('2 read beta outline', (await ask('view_dlg', { dialog: 'beta' })).replace(/[0-9a-f]{8}:/g, ''));
  exp('2 read beta outline', /n:Beta notes: findings so far c:beta_value = 1/);
  await ask('add_msg', { content: 'Summary written from alpha', msg_type: 'note', dialog: 'beta' });
  await beta.waitForTimeout(500);
  log('3 beta updated live, marked', await cells(beta));
  exp('3 beta updated live, marked', v => v.length === 3 && v[1].startsWith('code:beta_value = 1') && v[2] === 'note[AI]:Summary written from alpha');
  await ask('update_msg', { id: betaCode, content: 'beta_value = 2\nbeta_value', dialog: 'beta' });
  await beta.waitForTimeout(500);
  log('4 beta cell edited, marked, old output kept', [await cells(beta), await beta.$eval('#msgs > .msg.t-code .mout', e => e.innerText.trim())]);
  exp('4 beta cell edited, marked, old output kept', v => v[0][1].startsWith('code[AI]:beta_value = 2') && v[1] === '1');
  log('5 alpha itself unchanged', (await cells(alpha)).filter(c => !c.startsWith('prompt')));
  exp('5 alpha itself unchanged', []);
  log('6 run in another dialog refused', await ask('add_msg', { content: 'print("x")', msg_type: 'code', run: true, dialog: 'beta' }));
  exp('6 run in another dialog refused', /Code can only be run in the dialog you are in \(alpha\), not in beta/);
  log('7 unknown dialog', await ask('view_dlg', { dialog: 'nope' }));
  exp('7 unknown dialog', /No dialog named 'nope'/);
  await alpha.evaluate(() => fetch('/setup', { method: 'POST' }));   // make sure SETUP exists (a no-op if an earlier test created it)
  log('8 SETUP is off limits to the AI', await ask('add_msg', { content: 'import os; os.system("echo owned")', msg_type: 'code', dialog: 'SETUP' }));
  exp('8 SETUP is off limits to the AI', /only the user changes it/);
  log('8 SETUP file unchanged by the AI', !/owned/.test(await (await fetch('http://127.0.0.1:5001/d/SETUP/export/py')).text()));
  exp('8 SETUP file unchanged by the AI', true);
  log('8 AI may still read SETUP', (await ask('view_dlg', { dialog: 'SETUP' })).slice(0, 40));
  exp('8 AI may still read SETUP', /Project setup/);
  const added = (await cells(beta)).length;
  await ask('del_msg', { id: await beta.$eval('#msgs > .msg.t-note.by-ai', e => e.dataset.id), dialog: 'beta' }); await beta.waitForTimeout(500);
  log('9 delete in beta', [added, (await cells(beta)).length]);
  exp('9 delete in beta', [3, 2]);
  // the same functions from my own code
  await type(alpha, 'code', 'add_msg("from my own code", "note", dialog="beta")\nprint(list_dialogs())'); await beta.waitForTimeout(500);
  log('10 my code edits beta, unmarked', [(await cells(beta)).pop(), (await alpha.$eval('#msgs > .msg:last-child .mout', e => e.innerText)).replace(/\s+/g, ' ').slice(0, 60)]);
  exp('10 my code edits beta, unmarked', v => v[0] === 'note:from my own code' && /alpha \(this dialog\)/.test(v[1]));
  await beta.reload(); await beta.waitForSelector('.msg'); log('11 saved to beta file', await cells(beta));
  exp('11 saved to beta file', v => v.length === 3 && v[1].startsWith('code[AI]:beta_value = 2') && v[2] === 'note:from my own code');
  done(errs);
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 700)); process.exit(1); });
