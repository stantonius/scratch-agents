// Shared by the browser tests: log(label, value) prints what happened; exp(label, expected) says what it must be.
// `expected` is an exact value, a regular expression (tested against the printed form), or a function (value, printed) => boolean.
// done(errs) fails the run if any expectation failed, any logged value has no expectation, or the browser console had errors.
module.exports = () => {
  const vals = new Map(), checked = new Set(), fails = [];
  const show = v => typeof v === 'string' ? v : JSON.stringify(v);
  const log = (k, v) => { vals.set(k, v); console.log(k, '=>', show(v)); };
  const exp = (k, ok) => {
    checked.add(k);
    if (!vals.has(k)) return fails.push(`${k}: never logged`);
    const v = vals.get(k), s = show(v);
    const pass = typeof ok === 'function' ? !!ok(v, s) : ok instanceof RegExp ? ok.test(s) : (typeof ok === 'object' ? JSON.stringify(ok) === JSON.stringify(v) : v === ok);
    if (!pass) { fails.push(`${k}: got ${s.slice(0, 200)}`); console.log('  ^^^ WRONG, expected', ok instanceof RegExp || typeof ok === 'function' ? String(ok).slice(0, 160) : JSON.stringify(ok)); }
  };
  const done = errs => {
    console.log('ERRORS', JSON.stringify(errs));
    if (errs.length) fails.push('browser console errors: ' + JSON.stringify(errs).slice(0, 300));
    for (const k of vals.keys()) if (!checked.has(k)) fails.push(`${k}: logged but never checked`);
    if (fails.length) { console.log(`FAILED ${fails.length} check(s):\n  - ` + fails.join('\n  - ')); process.exit(1); }
    console.log(`ok: ${checked.size} checks passed`);
  };
  return { log, exp, done };
};
