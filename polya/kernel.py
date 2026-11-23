"""One Jupyter kernel per dialog, spoken to over the standard Jupyter protocol.

The kernel is `ipymini` (Answer.AI's small IPython kernel) by default; any installed kernelspec
works (`POLYA_KERNEL=python3` for ipykernel). `conkernelclient` is the client, and `ipyfuncs`
adds the kernel-side helpers (tool schemas, variable listing) used here.
"""
import asyncio, os
from conkernelclient import ConKernelManager

OUTPUT_TYPES = ('stream', 'display_data', 'execute_result', 'error', 'update_display_data', 'clear_output')
RESULT_LIMIT = 5000

STARTUP = """
import ipyfuncs
from polya.helper import *
from polya.helper import _call_tool as __polya_call
"""


class Kernel:
    def __init__(self, cwd, env, name=None):
        self.cwd, self.env = str(cwd), dict(env)
        self.name = name or os.environ.get('POLYA_KERNEL', 'py')
        self.sidecar = self.name == 'py'   # ipymini's side channel; other kernels use the main shell
        self.km = self.kc = None
        self.busy = 0
        self._starting = asyncio.Lock()

    @property
    def alive(self): return self.kc is not None

    async def ensure(self):
        async with self._starting:
            if self.kc is not None and await self.km.is_alive(): return self.kc
            await self._close()
            km = ConKernelManager(kernel_name=self.name)
            await km.start_kernel(cwd=self.cwd, env={**os.environ, **self.env})
            kc = await km.client().start_channels()
            await kc.exec_ok(STARTUP, store_history=False, timeout=60)
            self.km, self.kc = km, kc
            return kc

    async def run(self, code):
        "Async iterator over the output messages of running `code`."
        kc = await self.ensure()
        self.busy += 1
        try:
            async for m in kc.run(code, timeout=None):
                if m.get('channel') == 'iopub' and m['header']['msg_type'] in OUTPUT_TYPES: yield m
        finally: self.busy -= 1

    async def schemas(self, names):
        "Tool schemas for functions `names` in the kernel namespace: {name: schema-dict | error-string}."
        if not names: return {}
        kc = await self.ensure()
        res = await kc.get_schemas(list(names), sidecar_=self.sidecar)
        return res if isinstance(res, dict) else {n: str(res) for n in names}

    async def user_exprs(self, exprs):
        "Jupyter `user_expressions` records for `exprs` (what aihist wants for $`var` values)."
        if not exprs: return {}
        kc = await self.ensure()
        r = await kc.user_exprs({e: e for e in exprs}, timeout=30)
        return r.get('user_expressions') or {}

    async def call(self, name, args):
        "Call tool `name(**args)` in the kernel, returning its result as text."
        kc = await self.ensure()
        self.busy += 1
        try: res = await kc.eval('__polya_call', name, args, timeout_=3600)
        finally: self.busy -= 1
        res = res if isinstance(res, str) else repr(res)
        return res if len(res) <= RESULT_LIMIT else res[:RESULT_LIMIT] + f'… [truncated, {len(res) - RESULT_LIMIT} more chars]'

    async def user_items(self):
        "(variables, functions) defined by the user, for the sidebar."
        if self.kc is None: return {}, {}
        try: v, f = await self.kc.ipy('user_items', timeout_=5, sidecar_=self.sidecar)
        except Exception: return {}, {}
        return v, f

    async def complete(self, code, pos):
        if self.kc is None: return [], pos
        try: return await self.kc.complete(code, pos, timeout=5)
        except Exception: return [], pos

    async def interrupt(self):
        if self.kc is not None and self.busy:
            try: await self.kc.interrupt()
            except Exception: pass

    async def _close(self):
        km, kc, self.km, self.kc = self.km, self.kc, None, None
        if kc is not None:
            try: kc.stop_channels()
            except Exception: pass
        if km is not None:
            try: await km.shutdown_kernel(now=True)
            except Exception: pass

    async def shutdown(self):
        "Stop the kernel (even mid-run). A fresh one starts on next use."
        async with self._starting: await self._close()
