import asyncio, sys, json
from mcpmini.core import MCPClient
tok = open(sys.argv[1]).read().strip()
async def main():
    async with MCPClient.http('http://127.0.0.1:5001/mcp', token=tok) as c:
        t = c.tools
        print('TOOLS', sorted(n for n in dir(t) if not n.startswith('_'))[:14])
        print('1 list ->', (await t.list_dialogs()).replace('\n', ' | '))
        print('2 outline ->', (await t.view_dlg(dialog='welcome')).splitlines()[:2])
        r = await t.add_msg(dialog='welcome', content='Checking how order totals are computed. Expect 14.4 for one item at 12.', msg_type='note'); print('3 note ->', r)
        r = await t.add_msg(dialog='welcome', content='from acme.orders import Order, order_total\no = Order([(12.0, 1)])\norder_total(o)', msg_type='code', run=True); print('4 code+run ->', r.replace('\n', ' | '))
        aid = r.split()[2].rstrip('.')
        print('5 state ->', (await t.kernel_state(dialog='welcome')).replace('\n', ' | ')[:200])
        print('6 source ->', (await t.source_of(dialog='welcome', symbol='order_total')).replace('\n', ' | ')[:230])
        print('7 edit own ->', await t.update_msg(dialog='welcome', id=aid, content='order_total(Order([(10.0, 2)]))'))
        print('8 rerun ->', await t.run_msg(dialog='welcome', id=aid))
        first = (await t.view_dlg(dialog='welcome')).splitlines()[0].split(':')[0]
        for label, call in [('9 edit user msg', lambda: t.update_msg(dialog='welcome', id=first, content='hacked')), ('10 delete user msg', lambda: t.del_msg(dialog='welcome', id=first)), ('11 prompt type', lambda: t.add_msg(dialog='welcome', content='x', msg_type='prompt'))]:
            try: print(label, '-> ALLOWED?!', str(await call())[:150])
            except Exception as e: print(label, '-> refused:', str(e)[:150])
    async with MCPClient.http('http://127.0.0.1:5001/mcp', token=tok) as c:
        t = c.tools
        print('13 create_dialog ->', (await t.create_dialog(dialog='agent-flow'))[:32])
        await t.add_msg(dialog='agent-flow', content='# Order totals\n1. order_total\n2. Order.subtotal\n3. with_tax', msg_type='note')
        print('14 add_source ->', [(await t.add_source(dialog='agent-flow', symbol=sy, file=f)).split(': ', 1)[1] for sy, f in [('order_total', 'acme/orders.py'), ('Order.subtotal', 'acme/orders.py'), ('with_tax', 'acme/pricing.py')]])
        print('15 outline ->', [l.split(':', 2)[1] + ':' + l.split(':', 2)[2][:22] for l in (await t.view_dlg(dialog='agent-flow')).splitlines()])
        try: await t.add_source(dialog='agent-flow', symbol='nope', file='acme/orders.py'); print('16 unknown symbol -> ALLOWED?!')
        except Exception as e: print('16 unknown symbol -> refused')
        try: await t.create_dialog(dialog='agent-flow'); print('17 duplicate dialog -> ALLOWED?!')
        except Exception as e: print('17 duplicate dialog -> refused')
    try:
        async with MCPClient.http('http://127.0.0.1:5001/mcp', token='wrong') as c: await c.tools.list_dialogs(); print('12 wrong token -> ALLOWED?!')
    except Exception as e: print('12 wrong token -> refused:', type(e).__name__, str(e)[:80])
asyncio.run(main())
