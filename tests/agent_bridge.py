"""The coding-agent bridge, driven the way an agent would: over MCP with the token from the dialogs folder.

Usage: python tests/agent_bridge.py <path to .polya-agent-token>
Needs the server started with --project pointing at a copy of tests/sample_project.
Every line printed is checked; the script exits 1 if any check fails.
"""
import asyncio, re, sys

from mcpmini.core import MCPClient

URL = 'http://127.0.0.1:5001/mcp'
tok = open(sys.argv[1]).read().strip()
fails = []


def check(label, value, ok):
    "Print what happened and record a failure unless `ok` (a regex, an exact value, or a predicate) accepts it."
    s = value if isinstance(value, str) else repr(value)
    good = bool(re.search(ok, s)) if isinstance(ok, str) else (ok(value) if callable(ok) else value == ok)
    print(('  ' if good else 'X ') + label, '->', s.replace('\n', ' | ')[:230])
    if not good: fails.append(label)


async def refused(label, call, why):
    "The call must raise, and the reason must mention `why`."
    try: check(label, 'ALLOWED: ' + str(await call())[:120], lambda v: False)
    except Exception as e: check(label, 'refused: ' + str(e).strip().splitlines()[-1][:160], why)


async def main():
    async with MCPClient.http(URL, token=tok) as c:
        t = c.tools
        check('0 tools', sorted(n for n in ('list_dialogs create_dialog view_dlg read_msg find_msgs add_source add_msg run_msg update_msg del_msg kernel_state source_of'.split()) if hasattr(t, n)),
              lambda v: len(v) == 12)
        check('1 list', await t.list_dialogs(), r'welcome')
        check('2 outline', await t.view_dlg(dialog='welcome'), r'^[0-9a-f]{8}:n:# Welcome to Polya')
        nid = await t.add_msg(dialog='welcome', content='Checking how order totals are computed. Expect 14.4 for one item at 12.', msg_type='note')
        check('3 note added', nid, r'^[0-9a-f]{8}$')
        r = await t.add_msg(dialog='welcome', content='from acme.orders import Order, order_total\no = Order([(12.0, 1)])\norder_total(o)', msg_type='code', run=True)
        check('4 code added and run in the project', r, r'^Added message [0-9a-f]{8}\. Output:\n14\.4$')
        aid = r.split()[2].rstrip('.')
        check('5 kernel state', await t.kernel_state(dialog='welcome'), r'o = <acme\.orders\.Order object')
        check('6 source as loaded', await t.source_of(dialog='welcome', symbol='order_total'), r'acme/orders\.py:11\ndef order_total\(order: Order\) -> float:')
        check('7 edit own cell', await t.update_msg(dialog='welcome', id=aid, content='order_total(Order([(10.0, 2)]))'), f'Updated message {aid}')
        check('8 rerun own cell', await t.run_msg(dialog='welcome', id=aid), '24.0')
        check('8 cells are marked as the agent\'s', await t.view_dlg(dialog='welcome', full=True), lambda v: aid in v and nid in v)
        first = (await t.view_dlg(dialog='welcome')).splitlines()[0].split(':')[0]
        await refused('9 edit a user cell', lambda: t.update_msg(dialog='welcome', id=first, content='hacked'), r'written by the user')
        await refused('10 delete a user cell', lambda: t.del_msg(dialog='welcome', id=first), r'written by the user')
        await refused('11 add a prompt', lambda: t.add_msg(dialog='welcome', content='x', msg_type='prompt'), r"must be 'note' or 'code'")
        check('11 user cell untouched', await t.read_msg(dialog='welcome', id=first), lambda v: 'Welcome to Polya' in v and 'hacked' not in v)

        check('13 create_dialog', await t.create_dialog(dialog='agent-flow'), r"^Created dialog 'agent-flow'")
        await t.add_msg(dialog='agent-flow', content='# Order totals\n1. order_total\n2. Order.subtotal\n3. with_tax', msg_type='note')
        links = [(await t.add_source(dialog='agent-flow', symbol=sy, file=f)).split(': ', 1)[1]
                 for sy, f in [('order_total', 'acme/orders.py'), ('Order.subtotal', 'acme/orders.py'), ('with_tax', 'acme/pricing.py')]]
        check('14 add_source links cells to files', links,
              ['linked to acme/orders.py :: order_total (3 lines)', 'linked to acme/orders.py :: Order.subtotal (2 lines)', 'linked to acme/pricing.py :: with_tax (3 lines)'])
        check('15 code was copied from the files', await t.view_dlg(dialog='agent-flow', full=True),
              lambda v: all(x in v for x in ('return with_tax(order.subtotal())', 'return sum(price * qty for price, qty in self.items)', 'return round(amount * (1 + TAX), 2)')))
        await refused('16 unknown symbol', lambda: t.add_source(dialog='agent-flow', symbol='nope', file='acme/orders.py'), r'not defined in')
        await refused('17 duplicate dialog', lambda: t.create_dialog(dialog='agent-flow'), r'already exists')
        await refused('18 unknown dialog', lambda: t.view_dlg(dialog='no-such-dialog'), r'No dialog named')
    try:
        async with MCPClient.http(URL, token='wrong') as c: await c.tools.list_dialogs()
        check('12 wrong token', 'ALLOWED', lambda v: False)
    except Exception as e: check('12 wrong token', f'refused: {type(e).__name__} {e}'[:90], r'401')
    if fails:
        print(f'FAILED {len(fails)} check(s): ' + ' | '.join(fails))
        sys.exit(1)
    print('ok: all checks passed')

asyncio.run(main())
