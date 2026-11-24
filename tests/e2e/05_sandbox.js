// "AI can run code": the python and bash tools run in the kernel's sandbox. Needs --project (tests/sample_project).
const { chromium } = require('playwright');
const out = process.argv[2];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  const idle = () => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 90000 });
  const type = async (kind, text) => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press('Control+Enter'); };
  const { log, exp, done } = require('./_check')();
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

  log('0 on by default in a new dialog', await p.isChecked('#ctools'));
  exp('0 on by default in a new dialog', true);
  await p.uncheck('#ctools'); await p.waitForTimeout(300);
  const seenTools = async () => ((await (await fetch('http://127.0.0.1:8765/seen')).json()).tools || []).map(t => t.function.name);
  await type('prompt', 'hello'); await p.waitForTimeout(1200); await idle();
  log('0 tools when off', await seenTools());
  exp('0 tools when off', []);
  await p.check('#ctools'); await p.waitForTimeout(300);

  log('1 python sees my kernel', tail(await ask('python', { code: 'print("sum", sum(data)); double(21)' })));
  exp('1 python sees my kernel', /returned: sum 16 42/);
  log('1 tools when on', await seenTools());
  exp('1 tools when on', ['python', 'bash', 'search_code', 'outline', 'read_lines', 'source_of']);
  log('2 python uses my project', tail(await ask('python', { code: 'from acme.pricing import with_tax\nwith_tax(100)' })));
  exp('2 python uses my project', /returned: 120\.0/);
  log('3 bash read-only', tail(await ask('bash', { cmd: 'ls acme | sort | head -3' })));
  exp('3 bash read-only', /orders\.py/);
  log('3 code search with rg', tail(await ask('bash', { cmd: 'rg -n "def with_tax" -t py' })));
  exp('3 code search with rg', /returned: acme\/pricing\.py:4:def with_tax/);
  // a long result reaches the model whole up to the limit, and is cut with a marker beyond it
  const toolMsg = async () => { const m = (await (await fetch('http://127.0.0.1:8765/seen')).json()).messages.filter(x => x.role === 'tool').pop(); return typeof m.content === 'string' ? m.content : JSON.stringify(m.content); };
  await ask('python', { code: 'print("x" * 15000)' });
  log('3 a 15,000 character result arrives whole', (await toolMsg()).length);
  exp('3 a 15,000 character result arrives whole', v => v >= 15000 && v < 15100);
  await ask('python', { code: 'print("HEAD" + "y" * 50000 + "TAIL")' });
  const big = await toolMsg();
  log('3 an over-long result keeps its start and end', [big.length < 20000, big.startsWith('HEAD'), big.trimEnd().endsWith('TAIL'), /characters left out of the middle/.test(big)]);
  exp('3 an over-long result keeps its start and end', [true, true, true, true]);
  // the focused tools return the part that answers the question, not whole files
  log('3 outline of a file', tail(await ask('outline', { file: 'acme/orders.py' })));
  exp('3 outline of a file', /acme\/orders\.py: 13 lines.*7-8\s+def subtotal\(self\).*11-13\s+def order_total/);
  log('3 search shows where, and how many', tail(await ask('search_code', { pattern: 'with_tax' })));
  exp('3 search shows where, and how many', /returned: 3 matches in 2 files\.\s*acme\/orders\.py:1: from acme\.pricing import with_tax/);
  log('3 search is capped with a count', tail(await ask('search_code', { pattern: 'e', max_results: 2 })));
  exp('3 search is capped with a count', /returned: 10 matches in 2 files; showing the first 2\./);
  log('3 a range of lines', tail(await ask('read_lines', { file: 'acme/orders.py', start: 11, count: 2 })));
  exp('3 a range of lines', /acme\/orders\.py lines 11-12 of 13\s+11\s+def order_total.*12\s+"Total for/);
  log('3 one function', tail(await ask('source_of', { name: 'acme.pricing.with_tax' })));
  exp('3 one function', /pricing\.py:4\s*def with_tax\(amount: float\) -> float:/);
  log('4 secrets not in kernel env', tail(await ask('python', { code: 'import os\n[k for k in os.environ if k in ("POLYA_API_KEY", "POLYA_AGENT_TOKEN")]' })));
  exp('4 secrets not in kernel env', /returned: \[\]/);

  let r = await ask('python', { code: 'import urllib.request\nurllib.request.urlopen("http://127.0.0.1:8765/seen").status' });
  log('5 network blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 90)); log('5 left as a cell', await lastCell());
  exp('5 network blocked', /BLOCKED by the sandbox/);
  exp('5 left as a cell', v => v.type === 'code' && v.byAI && /urllib/.test(v.src) && v.out === '');
  await p.click('#msgs > .msg:last-child .mhead'); await p.keyboard.press('Control+Enter'); await p.waitForTimeout(500); await idle();
  log('5 the human can run it', (await lastCell()).out);
  exp('5 the human can run it', '200');

  // (the sample project is copied under /tmp, the sandbox's scratch area, so the test writes to the home folder instead)
  r = await ask('python', { code: 'import os\nopen(os.path.expanduser("~/polya_written_by_ai.txt"), "w").write("x")' });
  log('6 write outside /tmp blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 80));
  exp('6 write outside /tmp blocked', /BLOCKED by the sandbox/);
  r = await ask('bash', { cmd: 'echo x > ~/polya_written_by_ai2.txt' });
  log('6 bash redirect outside /tmp blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 80));
  exp('6 bash redirect outside /tmp blocked', /BLOCKED by the sandbox/);
  log('6 nothing was written', !require('fs').existsSync(require('os').homedir() + '/polya_written_by_ai.txt') && !require('fs').existsSync(require('os').homedir() + '/polya_written_by_ai2.txt'));
  exp('6 nothing was written', true);
  r = await ask('python', { code: 'import subprocess\nsubprocess.run(["echo", "hi"])' });
  log('7 subprocess blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 70));
  exp('7 subprocess blocked', /BLOCKED by the sandbox/);
  r = await ask('bash', { cmd: 'curl -s http://127.0.0.1:8765/seen' });
  log('8 curl blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 90)); log('8 left as a cell', await lastCell());
  exp('8 curl blocked', /BLOCKED by the sandbox/);
  exp('8 left as a cell', v => v.type === 'code' && v.byAI && v.src.startsWith('%%bash\ncurl') && v.out === '');
  r = await ask('bash', { cmd: 'rm -rf acme' });
  log('9 rm blocked', r.slice(r.indexOf('BLOCKED'), r.indexOf('BLOCKED') + 70));
  exp('9 rm blocked', /BLOCKED by the sandbox/);
  log('9 project folder still there', tail(await ask('bash', { cmd: 'ls acme | wc -l' })));
  exp('9 project folder still there', /returned: [1-9]/);
  await p.screenshot({ path: out + '/08-sandbox.png' });

  // widening the sandbox is one line of your own code
  await type('code', 'sandbox_dirs("/tmp/polya_extra"); sandbox_cmds("curl"); import os; os.makedirs("/tmp/polya_extra", exist_ok=True)'); await p.waitForTimeout(500); await idle();
  log('10 curl after sandbox_cmds', tail(await ask('bash', { cmd: 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/seen' })));
  exp('10 curl after sandbox_cmds', /returned: 200/);
  log('10 write after sandbox_dirs', tail(await ask('python', { code: 'open("/tmp/polya_extra/ok.txt", "w").write("fine")' })));
  exp('10 write after sandbox_dirs', /returned: 4/);

  // with dialog tools too: a cell the AI adds with run=true runs in the sandbox, and shows its output
  await p.check('#dtools'); await p.waitForTimeout(300);
  r = await ask('add_msg', { content: 'print("ran sandboxed:", double(4))', msg_type: 'code', run: true });
  log('11 AI cell ran sandboxed', await lastCell());
  exp('11 AI cell ran sandboxed', v => v.byAI && /ran sandboxed: 8/.test(v.out));
  r = await ask('add_msg', { content: 'import subprocess\nsubprocess.run(["echo", "x"])', msg_type: 'code', run: true });
  log('12 AI cell blocked', await lastCell());
  exp('12 AI cell blocked', v => v.byAI && /Blocked by the sandbox/.test(v.out));
  // my own cells are never sandboxed
  await type('code', 'import subprocess\nsubprocess.run(["echo", "human cells are unrestricted"], capture_output=True, text=True).stdout'); await p.waitForTimeout(500); await idle();
  log('13 my cell', (await lastCell()).out);
  exp('13 my cell', /human cells are unrestricted/);
  done(errs);
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 700)); process.exit(1); });
