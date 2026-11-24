"""Run write-back over a large body of real Python and check it never touches anything it should not.

    python tests/corpus_check.py [--minutes N] [folder ...]

Default folders: the standard library and installed packages. Default budget: 10 minutes; when it runs
out the check stops and reports on what it covered. Progress is printed as it goes.

Files are copied to a temporary folder first; nothing outside it is written. For every function, class
and method in every file:
  1. it can be located, and its source read back from the file reports "in sync";
and for a sample of them per file (all of them in small files):
  2. writing it back unchanged leaves the file byte-for-byte identical;
  3. renaming it changes only lines inside its own span, the file still parses, and the renamed symbol
     is found where the old one was;
  4. renaming it back restores the original file byte-for-byte.
"""
import ast, random, shutil, sys, sysconfig, tempfile, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polya import source as so

PER_FILE = 12


def check_file(root, rel, rng, stats, problems):
    path = root / rel
    try: syms = so.symbols(path)
    except so.SourceError: stats['skipped: does not parse or decode'] += 1; return
    original = path.read_bytes()
    links = {}
    for q in syms:
        stats['symbols'] += 1
        try:
            lk, src = so.link(path, q, root)
            links[q] = (lk, src)
            st = so.status(lk, src, root)[0]
            if st != 'sync': problems.append((rel, q, f'fresh link reports {st}'))
        except Exception as e: problems.append((rel, q, f'link failed: {type(e).__name__}: {e}'))
    for q in (syms if len(syms) <= PER_FILE else rng.sample(syms, PER_FILE)):
        if q not in links: continue
        lk, src = links[q]
        stats['round trips'] += 1
        try:
            try: so.one_def(src)
            except so.SourceError: stats['skipped: source is not one definition when dedented'] += 1; continue
            so.apply(lk, src, root)                                   # 2. identity
            if path.read_bytes() != original:
                problems.append((rel, q, 'writing it back unchanged altered the file')); path.write_bytes(original); continue
            name = q.split('#')[0].rsplit('.', 1)[-1]
            new = name + '_polyacheck'
            node = so.one_def(src)
            lines = src.split('\n')
            i = node.lineno - 1
            if f' {name}' not in lines[i]: stats['skipped: name not on its def line'] += 1; continue
            lines[i] = lines[i].replace(f' {name}', f' {new}', 1)
            lk2, body = so.apply(lk, '\n'.join(lines), root)          # 3. rename
            changed = path.read_bytes()
            span = so.find(path, lk2['qualname'])
            if span is None: problems.append((rel, q, f'after renaming, {lk2["qualname"]} was not found')); path.write_bytes(original); continue
            a, b = so._split(original.decode(so.parsed(path)['enc']))[0], so._split(changed.decode(so.parsed(path)['enc']))[0]
            if len(a) != len(b) or any(x != y for k, (x, y) in enumerate(zip(a, b)) if not span['start'] - 1 <= k < span['end']):
                problems.append((rel, q, 'renaming changed lines outside the symbol'))
            ast.parse(changed)
            lk3, _ = so.apply(lk2, body.replace(f' {new}', f' {name}', 1), root)     # 4. and back
            if path.read_bytes() != original: problems.append((rel, q, 'renaming back did not restore the file'))
        except Exception as e: problems.append((rel, q, f'{type(e).__name__}: {str(e)[:160]}'))
        finally:
            if path.read_bytes() != original: path.write_bytes(original)


def main(folders, minutes=10):
    rng, stats, problems, t0 = random.Random(0), Counter(), [], time.time()
    deadline, out_of_time = t0 + minutes * 60, False
    tmp = Path(tempfile.mkdtemp())
    for n, folder in enumerate(folders):
        root = tmp / f'c{n}'
        shutil.copytree(folder, root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so', 'node_modules'), symlinks=False, ignore_dangling_symlinks=True)
        paths = sorted(root.rglob('*.py'))
        rng.shuffle(paths)             # so a run cut short by the budget still covers a spread of packages
        print(f'{folder}: {len(paths):,} files', flush=True)
        for path in paths:
            if time.time() > deadline: out_of_time = True; break
            stats['files'] += 1
            if stats['files'] % 250 == 0: print(f"  {stats['files']:,} files, {stats['symbols']:,} symbols, {stats['round trips']:,} round trips, {len(problems)} problems, {time.time() - t0:.0f}s", flush=True)
            ends = Counter(e for e in so._split(path.read_bytes().decode('latin-1'))[1] if e)
            if '\r\n' in ends: stats['files with CRLF'] += 1
            if path.read_bytes()[:3] == b'\xef\xbb\xbf': stats['files with a BOM'] += 1
            if b'\t' in path.read_bytes(): stats['files with tabs'] += 1
            check_file(root, path.relative_to(root), rng, stats, problems)
    shutil.rmtree(tmp, ignore_errors=True)
    for k, v in stats.items(): print(f'{v:>8,}  {k}')
    kinds = Counter(p[2].split(':')[0] for p in problems)
    print(f'{len(problems):>8,}  problems' + ''.join(f'\n            {v:>5,}  {k}' for k, v in kinds.most_common(8)))
    for rel, q, why in problems[:12]: print(f'     {rel} :: {q}: {why}')
    print(f'{time.time() - t0:.0f}s' + (f'  (stopped at the {minutes}-minute budget: not every file was reached)' if out_of_time else '  (every file reached)'))
    return 1 if problems else 0


if __name__ == '__main__':
    argv, minutes = sys.argv[1:], 10
    if '--minutes' in argv: i = argv.index('--minutes'); minutes = float(argv[i + 1]); del argv[i:i + 2]
    sys.exit(main([Path(a) for a in argv] or [Path(sysconfig.get_paths()['stdlib']), Path(sysconfig.get_paths()['purelib'])], minutes))
