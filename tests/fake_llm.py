"""A fake OpenAI-compatible chat endpoint for tests and offline demos. It is scripted, not a model.

- If the last user text contains `[[call NAME {json args}]]` and tool NAME was offered, it calls it,
  then (after the tool result comes back) replies "Tool NAME returned: <result>".
- Otherwise it streams a short canned reply containing a fenced python block.

Run: python tests/fake_llm.py [port]
"""
import json, re, sys, time, uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse, JSONResponse
from starlette.routing import Route

seen = []   # request bodies, for assertions


def _text(m):
    c = m.get('content')
    if isinstance(c, list): return '\n'.join(p.get('text', '') for p in c if isinstance(p, dict))
    return c or ''


def _chunk(delta, finish=None):
    d = dict(id='chatcmpl-fake', object='chat.completion.chunk', created=int(time.time()), model='fake',
             choices=[dict(index=0, delta=delta, finish_reason=finish)])
    return f'data: {json.dumps(d)}\n\n'


async def chat(req):
    body = await req.json()
    seen.append(body)
    msgs, tools = body['messages'], {t['function']['name'] for t in body.get('tools') or []}
    last = msgs[-1]

    def gen():
        yield _chunk(dict(role='assistant', content=''))
        if last['role'] == 'tool':
            call = next(tc for m in reversed(msgs) if m['role'] == 'assistant' for tc in m.get('tool_calls') or [])
            words = f"Tool {call['function']['name']} returned: {_text(last)}".split(' ')
        else:
            user = _text(last)
            m = re.search(r'\[\[call (\w+) (\{.*?\})\]\]', user, flags=re.S)
            if m and m.group(1) in tools:
                yield _chunk(dict(tool_calls=[dict(index=0, id='call_fake1', type='function',
                                                   function=dict(name=m.group(1), arguments=''))]))
                args = m.group(2)
                for i in range(0, len(args), 7):
                    yield _chunk(dict(tool_calls=[dict(index=0, function=dict(arguments=args[i:i + 7]))]))
                yield _chunk({}, 'tool_calls')
                yield 'data: [DONE]\n\n'
                return
            words = "Here is one small step to try:\n\n```python\nsorted(l1)\n```\n\nRun it and tell me what you see.".split(' ')
        for i, w in enumerate(words):
            time.sleep(0.01)
            yield _chunk(dict(content=w + (' ' if i < len(words) - 1 else '')))
        yield _chunk({}, 'stop')
        yield 'data: [DONE]\n\n'
    if not body.get('stream'):
        return JSONResponse(dict(id='x', object='chat.completion', model='fake', choices=[dict(
            index=0, finish_reason='stop', message=dict(role='assistant', content='non-streaming reply'))],
            usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
    return StreamingResponse(gen(), media_type='text/event-stream')


async def last(req): return JSONResponse(seen[-1] if seen else {})


app = Starlette(routes=[Route('/seen', last), Route('/v1/chat/completions', chat, methods=['POST']), Route('/chat/completions', chat, methods=['POST'])])

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765, log_level='warning')
