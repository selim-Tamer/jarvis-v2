import test from 'node:test';
import assert from 'node:assert/strict';
import {requestJson} from './src/api.ts';

test('HTTP failures cannot become Done', async () => {
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async()=>new Response(JSON.stringify({detail:'GEMINI_API_KEY is missing'}),{status:503});
    await assert.rejects(()=>requestJson('/api/chat'),/GEMINI_API_KEY is missing/);
    globalThis.fetch=async()=>new Response('<html>server error</html>',{status:500});
    await assert.rejects(()=>requestJson('/api/chat'),/invalid response.*500/);
    globalThis.fetch=async()=>new Response(JSON.stringify({accepted:true}),{status:202});
    assert.deepEqual(await requestJson('/api/chat'),{accepted:true});
  } finally {globalThis.fetch=original;}
});
