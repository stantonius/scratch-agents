const { chromium } = require('playwright');
const { log, exp, done } = require('./_check')();
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg');
  await p.screenshot({ path: process.argv[2] + '/01-open.png' });
  await p.keyboard.press('Escape'); await p.focus('#msgs'); await p.keyboard.press('r');
  await p.waitForFunction(() => document.querySelectorAll('.t-code .mout pre').length >= 5, null, { timeout: 60000 });
  await p.waitForFunction(() => document.querySelector('#kstat').classList.contains('idle'), null, { timeout: 30000 });
  const outs = await p.$$eval('.t-code', els => els.map(e => [e.querySelector('.min').innerText.slice(0, 40), e.querySelector('.mout').innerText.slice(0, 60)]));
  log('1 outputs', outs);
  exp('1 outputs', v => v[0][1].includes("'3   4") && v[1][1].startsWith("['3   4'") && v[2][1].trim() === '[3, 4, 2, 1, 3, 3]' && v[3][1].trim() === '[1, 2, 3, 3, 3, 4]' && v[4][1].trim() === '[1, 2, 3, 3, 3, 4]');
  await p.screenshot({ path: process.argv[2] + '/02-ran.png' });
  done(errs);
  await b.close();
})().catch(e => { console.log('FAILED', e.message.slice(0, 600)); process.exit(1); });
