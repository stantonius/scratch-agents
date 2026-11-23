const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); }); p.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  await p.goto('http://127.0.0.1:5001/d/welcome'); await p.waitForSelector('.msg');
  await p.screenshot({ path: process.argv[2] + '/01-open.png' });
  await p.keyboard.press('Escape'); await p.focus('#msgs'); await p.keyboard.press('r');
  await p.waitForFunction(() => document.querySelectorAll('.t-code .mout pre').length >= 5, null, { timeout: 60000 });
  await p.waitForFunction(() => document.querySelector('#kstat').classList.contains('idle'), null, { timeout: 30000 });
  const outs = await p.$$eval('.t-code', els => els.map(e => [e.querySelector('.min').innerText.slice(0, 40), e.querySelector('.mout').innerText.slice(0, 60)]));
  console.log(JSON.stringify(outs, null, 0));
  await p.screenshot({ path: process.argv[2] + '/02-ran.png' });
  console.log('ERRORS', JSON.stringify(errs));
  await b.close();
})();
