// "AI can run code": the python and bash tools run in the kernel's sandbox. Needs --project (tests/sample_project).
const { chromium } = require('playwright');
const out = process.argv[2];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  const idle = () => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 90000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); };
  const log = (k, v) => console.log(k, '=>', typeof v === 'string' ? v : JSON.stringify(v));
  const count = () => p.$$eval('#msgs > .msg', e => e.length);
  // ask the (scripted) AI to make one tool call; returns the text of its reply
  const ask = async (tool, args) => {
    const n = await count();
    await type('prompt', `go [[call ${tool} ${JSON.stringify(args)}]]`);
    await p.waitForFunction(n => document.querySelectorAll('#msgs > .msg').length > n, n); await p.waitForTimeout(300); await idle();
    return p.$eval(`#msgs > .msg:nth-child(${n + 1}) .mout`, e => e.innerText.replace(/\s+/g, ' '));
  };
  const lastCell = () => p.$eval('#msgs > .msg:last-child', e => ({ type: e.dataset.type, byAI: e.className.includes('by-ai'), src: e.querySelector('.min').innerText.slice(0, 70), out: e.querySelector('.mout').innerText.replace(/\s+/g, ' ').slice(0, 110) }));
  const tail = s => s.slice(s.indexOf('returned:'), s.indexOf('returned:') + 150);
  await p.goto('http://127.0.0.1:5001/'); await p.fill('input[name=name]', 'sandbox'); await p.click('.newdlg button'); await p.waitForURL(/sandbox/);
  await type('code', 'data = [3, 4, 9]\ndef double(x): return x * 2'); await p.waitForTimeout(500); await idle();

  const seenTools = async () => ((await (await fetch('http://127.0.0.1:8765/seen')).json()).tools || []).map(t => t.function.name);
  await type('prompt', 'hello'); await p.waitForTimeout(1200); await idle();
  log('0 tools when off', await seenTools());
  await p.check('#ctools'); await p.waitForTimeout(300);

  log('1 python sees my kernel', tail(await ask('python', { code: 'print("sum", sum(data)); double(21)' })));
  log('1 tools when on', await seenTools());
  log('2 python uses my project', tail(await ask('python', { code: 'from acme.pricing import with_tax\nwith_tax(100)' })));
  log('3 bash read-only', tail(await ask('bash', { cmd: 'ls acme | sort | head -3' })));
  log('4 secrets not in kernel env', tail(await ask('python', { code: 'import os\n[k for k in os.environ if k in ("POLYA_API_KEY", "POLYA_AGENT_TOKEN")]' })));

  let r = await ask('python', { code: 'import urllib.request\nurllib.request.urlopen("http://127.0.0.1:8765/seen").status' });
  log('5 network blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 90)); log('5 left as a cell', await lastCell());
  await p.click('#msgs > .msg:last-child .mhead'); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(500); await idle();
  log('5 the human can run it', (await lastCell()).out);

  // (the sample project is copied under /tmp, the sandbox's scratch area, so the test writes to the home folder instead)
  r = await ask('python', { code: 'import os\nopen(os.path.expanduser("~/polya_written_by_ai.txt"), "w").write("x")' });
  log('6 write outside /tmp blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 80));
  r = await ask('bash', { cmd: 'echo x > ~/polya_written_by_ai2.txt' });
  log('6 bash redirect outside /tmp blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 80));
  r = await ask('python', { code: 'import subprocess\nsubprocess.run(["echo", "hi"])' });
  log('7 subprocess blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 70));
  r = await ask('bash', { cmd: 'curl -s http://127.0.0.1:8765/seen' });
  log('8 curl blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 90)); log('8 left as a cell', await lastCell());
  r = await ask('bash', { cmd: 'rm -rf acme' });
  log('9 rm blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 70));
  await p.screenshot({ path: out + '/08-sandbox.png' });

  // widening the sandbox is one line of your own code
  await type('code', 'sandbox_dirs("/tmp/polya_extra"); sandbox_cmds("curl"); import os; os.makedirs("/tmp/polya_extra", exist_ok=True)'); await p.waitForTimeout(500); await idle();
  log('10 curl after sandbox_cmds', tail(await ask('bash', { cmd: 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/seen' })));
  log('10 write after sandbox_dirs', tail(await ask('python', { code: 'open("/tmp/polya_extra/ok.txt", "w").write("fine")' })));

  // with dialog tools too: a cell the AI adds with run=true runs in the sandbox, and shows its output
  await p.check('#dtools'); await p.waitForTimeout(300);
  r = await ask('add_msg', { content: 'print("ran sandboxed:", double(4))', msg_type: 'code', run: true });
  log('11 AI cell ran sandboxed', await lastCell());
  r = await ask('add_msg', { content: 'import subprocess\nsubprocess.run(["echo", "x"])', msg_type: 'code', run: true });
  log('12 AI cell blocked', await lastCell());
  // my own cells are never sandboxed
  await type('code', 'import subprocess\nsubprocess.run(["echo", "human cells are unrestricted"], capture_output=True, text=True).stdout'); await p.waitForTimeout(500); await idle();
  log('13 my cell', (await lastCell()).out);
  console.log('ERRORS', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 700)); process.exit(1); });
