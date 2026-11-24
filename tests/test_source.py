"""Edge cases for linking cells to files and writing them back (polya/source.py).

No server, browser or kernel needed:  python tests/test_source.py   (or pytest tests/test_source.py)

The property under test, again and again: writing one function back changes that function's lines
and nothing else in the file.
"""
import ast, sys, tempfile, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polya import source as so


def proj(files):
    "A temporary project; `files` maps relative paths to bytes or str. Returns its root."
    root = Path(tempfile.mkdtemp())
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return root


def edit(root, rel, name, old, new, **kw):
    "Link `name`, replace `old` with `new` in its source, write it back. Returns (link, file bytes after)."
    lk, src = so.link(root / rel, name, root)
    assert old in src, (old, src)
    lk2, _ = so.apply(lk, src.replace(old, new), root, **kw)
    return lk2, (root / rel).read_bytes()


def refuses(fn, why):
    try: fn()
    except so.SourceError as e: assert why in str(e), f'refused, but for another reason: {e}'
    else: raise AssertionError(f'should have been refused ({why})')


# ---------------------------------------------------------------- nothing but the function changes
def test_crlf_file_keeps_crlf_everywhere():
    before = b'import os\r\n\r\n\r\ndef a(x):\r\n    return x + 1\r\n\r\n\r\ndef b(y):\r\n    return y   \r\n'
    root = proj({'m.py': before})
    _, after = edit(root, 'm.py', 'a', 'x + 1', 'x + 2')
    assert after == before.replace(b'x + 1', b'x + 2')
    assert b'\n' not in after.replace(b'\r\n', b'')


def test_lf_file_stays_lf():
    before = b'def a(x):\n    return x + 1\n\n\ndef b(y):\n    return y\n'
    _, after = edit(proj({'m.py': before}), 'm.py', 'a', 'x + 1', 'x + 2')
    assert after == before.replace(b'x + 1', b'x + 2') and b'\r' not in after


def test_mixed_endings_untouched_lines_keep_their_own():
    before = b'def a(x):\r\n    return x + 1\r\n\r\n\r\ndef b(y):\n    return y\n\n\ndef c(z):\r\n    return z\r\n'
    _, after = edit(proj({'m.py': before}), 'm.py', 'b', 'return y', 'return y * 2')
    assert after.startswith(b'def a(x):\r\n    return x + 1\r\n\r\n\r\n') and after.endswith(b'\n\n\ndef c(z):\r\n    return z\r\n')


def test_no_trailing_newline_is_preserved():
    before = b'def a(x):\n    return x + 1\n\n\ndef b(y):\n    return y'
    root = proj({'m.py': before})
    _, after = edit(root, 'm.py', 'b', 'return y', 'return y * 2')
    assert after == b'def a(x):\n    return x + 1\n\n\ndef b(y):\n    return y * 2'
    _, after = edit(root, 'm.py', 'a', 'x + 1', 'x + 2')
    assert after == b'def a(x):\n    return x + 2\n\n\ndef b(y):\n    return y * 2'


def test_trailing_whitespace_and_comments_elsewhere_survive():
    before = b'# header   \nX = 1  \n\n# about a\ndef a(x):\n    return x + 1\n# after a\n\n\ndef b(y):   \n    return y\t\n'
    _, after = edit(proj({'m.py': before}), 'm.py', 'a', 'x + 1', 'x + 2')
    assert after == before.replace(b'x + 1', b'x + 2')


def test_tab_indented_class_gets_tabs():
    before = b'class K:\n\tdef m(self):\n\t\treturn 1\n\n\tdef n(self):\n\t\treturn 2\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'K.n', root)
    so.apply(lk, 'def n(self):\n\treturn 3', root)
    after = (root / 'm.py').read_bytes()
    assert after == before.replace(b'return 2', b'return 3'), after
    ast.parse(after)


def test_bom_is_kept():
    before = b'\xef\xbb\xbfdef a(x):\r\n    return x + 1\r\n'
    _, after = edit(proj({'m.py': before}), 'm.py', 'a', 'x + 1', 'x + 2')
    assert after == before.replace(b'x + 1', b'x + 2')


def test_latin1_coding_line_is_respected():
    before = '# -*- coding: latin-1 -*-\nNAME = "caf\xe9"\n\n\ndef a(x):\n    return x + 1\n'.encode('latin-1')
    _, after = edit(proj({'m.py': before}), 'm.py', 'a', 'x + 1', 'x + 2')
    assert after == before.replace(b'x + 1', b'x + 2') and b'caf\xe9' in after


def test_form_feed_does_not_shift_lines():
    before = b'def a(x):\n    return x + 1\n\x0c\ndef b(y):\n    return y\n'
    _, after = edit(proj({'m.py': before}), 'm.py', 'b', 'return y', 'return y * 2')
    assert after == before.replace(b'return y', b'return y * 2')


def test_writing_the_same_thing_twice_changes_nothing():
    root = proj({'m.py': b'def a(x):\r\n    return x + 1\r\n'})
    lk, once = edit(root, 'm.py', 'a', 'x + 1', 'x + 2')
    src = so.find(root / 'm.py', 'a')['source']
    assert so.status(lk, src, root)[0] == 'sync'
    so.apply(lk, src, root)
    assert (root / 'm.py').read_bytes() == once


def test_lines_you_did_not_change_inside_the_function_are_kept_exactly():
    # trailing spaces, a blank line that holds indentation, and an oddly indented comment: none are yours to change
    before = b'def a(x):   \n    y = x + 1  \n    \n      # odd comment\n    z = y * 2\n    return z\n\n\ndef b(): pass\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'a', root)
    so.apply(lk, src, root)
    assert (root / 'm.py').read_bytes() == before                      # unchanged cell: identical file
    so.apply(lk, src.replace('z = y * 2', 'z = y * 3'), root)
    assert (root / 'm.py').read_bytes() == before.replace(b'z = y * 2', b'z = y * 3')    # one line changed: one line differs


def test_text_inside_a_multiline_string_is_not_reindented():
    before = b'class K:\n    def q(self):\n        return """\nSELECT *\n  FROM t   \n"""\n\n    def n(self):\n        return 2\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'K.q', root)                       # a string line at column 0 inside a method
    assert src.split('\n')[0] == 'def q(self):' and 'SELECT *' in src
    so.one_def(src)
    so.apply(lk, src, root)
    assert (root / 'm.py').read_bytes() == before
    lk2, _ = so.apply(lk, src.replace('def q(self):', 'def q(self, extra=None):'), root)
    assert (root / 'm.py').read_bytes() == before.replace(b'def q(self):', b'def q(self, extra=None):')


def test_added_and_removed_lines_leave_their_neighbours_alone():
    before = b'def a(x):\n    one = 1  \n    two = 2  \n    return one + two\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'a', root)
    lk2, body = so.apply(lk, src.replace('    two = 2  \n', '    two = 2  \n    three = 3\n'), root)
    assert (root / 'm.py').read_bytes() == b'def a(x):\n    one = 1  \n    two = 2  \n    three = 3\n    return one + two\n'
    so.apply(lk2, body.replace('    one = 1  \n', ''), root)
    assert (root / 'm.py').read_bytes() == b'def a(x):\n    two = 2  \n    three = 3\n    return one + two\n'


# ---------------------------------------------------------------- finding the right thing
def test_decorators_belong_to_the_function():
    before = b'import functools\n\n\n@functools.cache\n@staticmethod\ndef a(x):\n    return x + 1\n\n\ndef b(): pass\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'a', root)
    assert src.startswith('@functools.cache\n@staticmethod\ndef a')
    so.apply(lk, src.replace('@staticmethod\n', '').replace('x + 1', 'x + 2'), root)
    assert (root / 'm.py').read_bytes() == b'import functools\n\n\n@functools.cache\ndef a(x):\n    return x + 2\n\n\ndef b(): pass\n'


def test_property_and_setter_are_addressed_separately():
    before = b'class T:\n    @property\n    def v(self):\n        return self._v\n\n    @v.setter\n    def v(self, x):\n        self._v = x\n'
    root = proj({'m.py': before})
    assert so.symbols(root / 'm.py') == ['T', 'T.v', 'T.v#2']
    lk, after = edit(root, 'm.py', 'T.v#2', 'self._v = x', 'self._v = int(x)')
    assert after == before.replace(b'self._v = x', b'self._v = int(x)') and lk['qualname'] == 'T.v#2'
    assert so.find(root / 'm.py', 'T.v')['source'].startswith('@property')


def test_overloads_are_addressed_separately():
    src = 'from typing import overload\n\n\n@overload\ndef f(x: int) -> int: ...\n@overload\ndef f(x: str) -> str: ...\ndef f(x):\n    return x\n'
    root = proj({'m.py': src})
    assert so.symbols(root / 'm.py') == ['f', 'f#2', 'f#3']
    _, after = edit(root, 'm.py', 'f#3', 'return x', 'return x or None')
    assert after.decode() == src.replace('return x\n', 'return x or None\n')


def test_definitions_under_if_and_try_are_found():
    src = 'import sys\n\nif sys.platform == "win32":\n    def impl():\n        return "w"\nelse:\n    def impl():\n        return "p"\n\ntry:\n    import fast\nexcept ImportError:\n    def fallback():\n        return 0\n'
    root = proj({'m.py': src})
    assert so.symbols(root / 'm.py') == ['impl', 'impl#2', 'fallback']
    _, after = edit(root, 'm.py', 'impl#2', 'return "p"', 'return "posix"')
    assert after.decode() == src.replace('return "p"', 'return "posix"')
    _, after = edit(root, 'm.py', 'fallback', 'return 0', 'return -1')
    assert '        return -1\n' in after.decode()


def test_nested_class_method_async_and_one_liner():
    src = 'class Outer:\n    class Inner:\n        async def m(self):\n            return 1\n\n    def one(self): return 1\n'
    root = proj({'m.py': src})
    assert so.symbols(root / 'm.py') == ['Outer', 'Outer.Inner', 'Outer.Inner.m', 'Outer.one']
    _, after = edit(root, 'm.py', 'Outer.Inner.m', 'return 1', 'return 2')
    assert '            return 2\n' in after.decode()
    _, after = edit(root, 'm.py', 'Outer.one', 'return 1', 'return 3')
    assert after.decode().endswith('    def one(self): return 3\n')


def test_multiline_signature_and_a_docstring_that_looks_like_code():
    src = 'def a(\n    x: int,\n    y: int = 2,\n) -> int:\n    """Example::\n\n        def fake():\n            pass\n    """\n    return x + y\n\n\ndef fake():\n    return "real"\n'
    root = proj({'m.py': src})
    assert so.symbols(root / 'm.py') == ['a', 'fake']
    _, after = edit(root, 'm.py', 'fake', '"real"', '"still real"')
    assert after.decode() == src.replace('"real"', '"still real"')


def test_functions_inside_functions_are_not_separate_targets():
    root = proj({'m.py': 'def outer():\n    def inner():\n        return 1\n    return inner\n'})
    assert so.symbols(root / 'm.py') == ['outer']
    assert 'def inner' in so.find(root / 'm.py', 'outer')['source']


def test_rename_follows_the_new_name():
    root = proj({'m.py': 'class K:\n    def old(self):\n        return 1\n'})
    lk, src = so.link(root / 'm.py', 'K.old', root)
    lk2, body = so.apply(lk, src.replace('def old', 'def new'), root)
    assert lk2['qualname'] == 'K.new' and so.status(lk2, body, root)[0] == 'sync'


# ---------------------------------------------------------------- status
def test_status_tells_who_changed_what():
    root = proj({'m.py': 'def a(x):\n    return x + 1\n'})
    lk, src = so.link(root / 'm.py', 'a', root)
    mine = src.replace('x + 1', 'x + 2')
    assert so.status(lk, src, root)[0] == 'sync' and so.status(lk, mine, root)[0] == 'edited'
    (root / 'm.py').write_text('def a(x):\n    return x + 9\n')
    assert so.status(lk, src, root)[0] == 'disk' and so.status(lk, mine, root)[0] == 'conflict'
    (root / 'm.py').write_text('def other(): pass\n')
    assert so.status(lk, src, root)[0] == 'missing'
    (root / 'm.py').unlink()
    assert so.status(lk, src, root)[0] == 'nofile'


def test_reformatting_whitespace_at_line_ends_is_not_a_change():
    root = proj({'m.py': b'def a(x):   \r\n    return x + 1  \r\n'})
    lk, src = so.link(root / 'm.py', 'a', root)
    assert so.status(lk, 'def a(x):\n    return x + 1\n\n', root)[0] == 'sync'


# ---------------------------------------------------------------- refusals
def test_refusals_leave_the_file_alone():
    before = b'def a(x):\n    return x + 1\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'a', root)
    refuses(lambda: so.apply(lk, src + '\n\ndef b():\n    pass\n', root), '2 functions or classes')
    refuses(lambda: so.apply(lk, 'x = 1', root), 'no function or class')
    refuses(lambda: so.apply(lk, src + '\nprint(a(1))\n', root), 'other statements')
    refuses(lambda: so.apply(lk, 'def a(x:\n    return', root), 'does not parse')
    (root / 'm.py').write_bytes(b'def a(x):\n    return x + 9\n')
    refuses(lambda: so.apply(lk, src.replace('x + 1', 'x + 2'), root), 'changed since this cell was linked')
    assert (root / 'm.py').read_bytes() == b'def a(x):\n    return x + 9\n'
    so.apply(lk, src.replace('x + 1', 'x + 2'), root, force=True)
    assert (root / 'm.py').read_bytes() == b'def a(x):\n    return x + 2\n'
    outside = proj({'o.py': before})
    refuses(lambda: so.apply(dict(file=str(outside / 'o.py'), qualname='a', sha=so.sha(src), kind='existing'), src, root), 'outside the project folder')
    refuses(lambda: so.link(root / 'm.py', 'nope', root), 'is not defined in')
    refuses(lambda: so.link(root / 'missing.py', 'a', root), 'No such file')


# ---------------------------------------------------------------- new code
def test_new_function_after_another_with_crlf():
    before = b'def a():\r\n    return 1\r\n\r\n\r\ndef c():\r\n    return 3\r\n'
    root = proj({'m.py': before})
    lk, _ = so.apply(dict(file='m.py', kind='new', after='a'), 'def b():\n    return 2', root)
    assert (root / 'm.py').read_bytes() == b'def a():\r\n    return 1\r\n\r\n\r\ndef b():\r\n    return 2\r\n\r\n\r\ndef c():\r\n    return 3\r\n'
    assert lk['qualname'] == 'b' and lk['kind'] == 'existing'


def test_new_method_after_a_method_goes_inside_the_class():
    root = proj({'m.py': 'class K:\n    def m(self):\n        return 1\n\n\ndef f():\n    pass\n'})
    lk, _ = so.apply(dict(file='m.py', kind='new', after='K.m'), 'def n(self):\n    return 2', root)
    assert (root / 'm.py').read_text() == 'class K:\n    def m(self):\n        return 1\n\n    def n(self):\n        return 2\n\n\ndef f():\n    pass\n'
    assert lk['qualname'] == 'K.n'


def test_new_function_at_the_end():
    root = proj({'a.py': 'def a():\n    return 1', 'b.py': 'def a():\n    return 1\n\n\n\n', 'empty.py': ''})
    for rel in ('a.py', 'b.py'):
        so.apply(dict(file=rel, kind='new', after=''), 'def z():\n    return 26', root)
        assert (root / rel).read_text() == 'def a():\n    return 1\n\n\ndef z():\n    return 26\n', rel
    so.apply(dict(file='empty.py', kind='new', after=''), 'def z():\n    return 26', root)
    assert (root / 'empty.py').read_text() == 'def z():\n    return 26\n'


def test_new_code_where_the_anchor_is_gone():
    root = proj({'m.py': 'def a():\n    return 1\n'})
    refuses(lambda: so.apply(dict(file='m.py', kind='new', after='gone'), 'def b():\n    return 2', root), 'is no longer in')


# ---------------------------------------------------------------- imports
def test_imports_go_to_the_import_block_in_the_files_style():
    before = b'import os\r\nimport sys\r\n\r\n\r\ndef a(x):\r\n    return x + 1\r\n'
    root = proj({'m.py': before})
    lk, src = so.link(root / 'm.py', 'a', root)
    lk2, body = so.apply(lk, 'import math\nimport os\n\n' + src.replace('x + 1', 'math.floor(x)'), root)
    assert (root / 'm.py').read_bytes() == b'import os\r\nimport sys\r\nimport math\r\n\r\n\r\ndef a(x):\r\n    return math.floor(x)\r\n'
    assert body.startswith('def a') and so.status(lk2, body, root)[0] == 'sync'


def test_imports_into_a_file_with_none():
    root = proj({'doc.py': '"""Docstring."""\nX = 1\n\n\ndef a():\n    return 1\n',
                 'hdr.py': '#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nX = 1\n\n\ndef a():\n    return 1\n',
                 'bare.py': 'def a():\n    return 1\n'})
    for rel, want in (('doc.py', '"""Docstring."""\nimport json\n\nX = 1\n'), ('hdr.py', '#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nimport json\n\nX = 1\n'), ('bare.py', 'import json\n\ndef a():\n')):
        lk, src = so.link(root / rel, 'a', root)
        so.apply(lk, 'import json\n\n' + src.replace('return 1', 'return json.dumps(1)'), root)
        text = (root / rel).read_text()
        assert text.startswith(want), (rel, text)
        ast.parse(text)


def test_an_import_the_cell_needs_shows_as_a_difference_until_written():
    root = proj({'m.py': 'def a(x):\n    return x\n'})
    lk, src = so.link(root / 'm.py', 'a', root)
    assert so.status(lk, 'import math\n\n' + src, root)[0] == 'edited'
    assert so.missing_imports(root / 'm.py', ['import math']) == ['import math']


if __name__ == '__main__':
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith('test_') and callable(f)]
    failed = 0
    for name, fn in tests:
        try: fn(); print('  ok  ', name)
        except Exception:
            failed += 1
            print('FAILED', name); traceback.print_exc(limit=3)
    print(f'{len(tests) - failed} of {len(tests)} passed')
    sys.exit(1 if failed else 0)
