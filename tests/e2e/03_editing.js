const { chromium } = require('playwright');
const out = process.argv[2];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  p.on('dialog', d => d.accept());
  const idle = () => p.waitForFunction(() => !document.querySelector('#kstat').classList.contains('busy') && !document.querySelector('.is-running'), null, { timeout: 40000 });
  const type = async (kind, text, key = 'Control+Enter') => { await p.click(`.ctype[data-type=${kind}]`); await p.keyboard.insertText(text); await p.keyboard.press(key); };
  const log = (k, v) => console.log(k, '=>', typeof v === 'string' ? v : JSON.stringify(v));
  const last = sel => p.$eval('#msgs > .msg:last-child ' + sel, e => e.innerText.replace(/\s+/g, ' ').slice(0, 160));
  // new dialog from the home page
  await p.goto('http://127.0.0.1:5001/'); await p.fill('input[name=name]', 'scratch test'); await p.click('.newdlg button');
  await p.waitForURL(/scratch%20test|scratch test/); log('1 new dialog url', p.url());
  await type('note', '# My problem\nSome *notes*.'); await p.waitForSelector('.t-note h1');
  await type('code', 'import matplotlib.pyplot as plt\nplt.plot([1,4,9]); plt.title("squares")'); await p.waitForTimeout(500); await idle();
  log('2 plot img', await p.$$eval('#msgs .o-img img', e => e.length));
  await type('code', 'import pandas as pd\npd.DataFrame({"a":[1,2],"b":[3,4]})'); await p.waitForTimeout(500); await idle();
  log('2 dataframe html', await p.$$eval('#msgs .o-html table', e => e.length));
  await type('code', 'zzz = 41\n1/0'); await p.waitForTimeout(500); await idle();
  log('3 error', (await last('.mout')).slice(-40));
  // completion from live kernel
  await p.click('.ctype[data-type=code]'); await p.waitForTimeout(1000); await p.keyboard.insertText('zz'); await p.keyboard.press('Tab'); await p.waitForTimeout(1200);
  log('4 completion', await p.$eval('#ceditor .CodeMirror', e => e.CodeMirror.getValue()));
  await p.keyboard.press('Control+a'); await p.keyboard.press('Backspace');
  // a / b, type switch, move, cut, paste
  await p.focus('#msgs'); await p.keyboard.press('Home'); await p.keyboard.press('b'); await p.waitForSelector('.msg.editing .CodeMirror');
  await p.keyboard.insertText('inserted below the heading'); await p.keyboard.press('Alt+k'); await p.waitForTimeout(700);
  await p.keyboard.press('Escape'); await p.waitForTimeout(500);
  log('5 order', await p.$$eval('#msgs > .msg', els => els.map(e => e.dataset.type + ':' + e.querySelector('.min').innerText.slice(0, 18).replace(/\n/g, ' '))));
  await p.keyboard.press('Alt+ArrowUp'); await p.waitForTimeout(400);
  log('5 after move up', await p.$$eval('#msgs > .msg', els => els.slice(0, 2).map(e => e.querySelector('.min').innerText.slice(0, 18).replace(/\n/g, ' '))));
  await p.keyboard.press('x'); await p.waitForTimeout(400); await p.keyboard.press('End'); await p.keyboard.press('v'); await p.waitForTimeout(500);
  log('5 after cut+paste', await p.$$eval('#msgs > .msg', els => els.map(e => e.querySelector('.min').innerText.slice(0, 14).replace(/\n/g, ' '))));
  await p.keyboard.press('2'); await p.waitForTimeout(400); log('5 heading', await p.$$eval('#msgs > .msg:last-child h2', e => e.length));
  // restart kernel: variables gone
  await p.keyboard.press('Shift+R'); await p.waitForTimeout(1500);
  await type('code', 'zzz'); await p.waitForTimeout(800); await idle();
  log('6 after restart', (await last('.mout')).slice(-45));
  // model endpoint failure is reported, not hidden
  await p.fill('#model', 'fake'); 
  await p.screenshot({ path: out + '/06-scratch.png' });
  // reload: everything persisted
  const before = await p.$$eval('#msgs > .msg', e => e.length); await p.reload(); await p.waitForSelector('.msg');
  log('7 persisted', [before, await p.$$eval('#msgs > .msg', e => e.length), await p.$$eval('#msgs .o-img img', e => e.length)]);
  console.log('ERRORS', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 700)); process.exit(1); });
