"""Offline bridge regression tests. No network API calls, audio, or real email."""
import asyncio
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import jarvis
from server import Runtime, create_app


class BridgeChecks(unittest.TestCase):
    def setUp(self):
        self.rt = Runtime(text_only=True)
        self.app = create_app(self.rt, start_worker=False)
        self.client = TestClient(self.app)
        self.client.get('/api/health')

    def test_empty_and_not_ready_requests_report_errors(self):
        self.assertEqual(self.client.post('/api/chat', json={'message':'hello'}).status_code,503)
        self.assertEqual(self.client.post('/api/chat', json={'message':'  '}).status_code,422)
        self.assertEqual(self.client.post('/api/chat', json={'message':'x'*12001}).status_code,422)

    def test_foreign_origin_cannot_control_the_laptop(self):
        r=self.client.post('/api/control',json={'action':'quit'},headers={'origin':'https://untrusted.example'})
        self.assertEqual(r.status_code,403)
        self.assertFalse(self.rt.stop.is_set())
        other=TestClient(self.app)
        self.assertEqual(other.post('/api/control',json={'action':'quit'}).status_code,403)

    def test_busy_and_confirmation_cannot_enqueue_typed_yes(self):
        self.rt.ready=True
        self.rt.busy=True
        self.assertEqual(self.client.post('/api/chat',json={'message':'yes'}).status_code,409)
        self.assertTrue(self.rt.typed.empty())
        self.rt.busy=False
        self.rt.voice=Mock(confirming=True)
        self.assertEqual(self.client.post('/api/chat',json={'message':'yes'}).status_code,409)

    def test_sse_response_is_real_stream_with_snapshot_and_state(self):
        self.rt.ui.log('jarvis','Visible reply')
        self.rt.stop.set()
        response=self.client.get('/api/events')
        self.assertEqual(response.status_code,200)
        self.assertIn('text/event-stream',response.headers['content-type'])
        frames=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        self.assertEqual(frames[0]['type'],'snapshot')
        self.assertEqual(frames[0]['messages'][0]['text'],'Visible reply')

    def test_worker_uses_core_and_preserves_history(self):
        assistant=Mock()
        assistant.ask.side_effect=lambda text:'Reply to '+text
        factory=Mock(return_value=assistant)
        rt=Runtime(text_only=True,assistant_factory=factory)
        with patch.dict(os.environ,{'GEMINI_API_KEY':'offline-fake-key'}):
            rt.start()
            deadline=time.monotonic()+3
            while not rt.ready and time.monotonic()<deadline:
                time.sleep(.01)
            rt.submit('hello')
            while not any(m['text']=='Reply to hello' for m in rt.messages) and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(any(m['text']=='Reply to hello' for m in rt.messages))
            rt.clear()
            rt.submit('fresh conversation')
            deadline=time.monotonic()+3
            while factory.call_count<2 and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual(factory.call_count,2)
            rt.close()
            rt.thread.join(2)
            self.assertFalse(rt.thread.is_alive())

    def test_controls_interrupt_and_quit_without_browser_close(self):
        self.assertEqual(self.client.post('/api/control',json={'action':'mute'}).status_code,200)
        self.assertTrue(self.rt.muted.is_set())
        self.client.post('/api/control',json={'action':'unmute'})
        self.assertFalse(self.rt.muted.is_set())
        self.client.post('/api/control',json={'action':'interrupt'})
        self.assertTrue(self.rt.interrupt.is_set())
        self.client.post('/api/control',json={'action':'quit'})
        self.assertTrue(self.rt.stop.is_set())

    def test_reply_must_be_visible_before_clearing(self):
        entered=threading.Event()
        release=threading.Event()
        assistant=Mock()
        assistant.ask.return_value='Final reply'
        rt=Runtime(text_only=True,assistant_factory=lambda voice:assistant)
        def delayed_reply(voice,text):
            entered.set()
            release.wait(2)
            voice.ui.log('jarvis',text)
        with patch.dict(os.environ,{'GEMINI_API_KEY':'offline-fake-key'}), patch.object(jarvis.Voice,'say',delayed_reply):
            rt.start()
            deadline=time.monotonic()+2
            while not rt.ready and time.monotonic()<deadline:
                time.sleep(.01)
            try:
                rt.submit('hello')
                self.assertTrue(entered.wait(2))
                self.assertTrue(rt.busy)
                with self.assertRaises(Exception) as raised:
                    rt.clear()
                self.assertEqual(raised.exception.status_code,409)
            finally:
                release.set()
                rt.close()
                rt.thread.join(2)

    def test_redacts_errors_before_streaming(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':'fake-secret'}):
            self.rt.ui.log('system','Request failed: fake-secret')
            self.assertNotIn('fake-secret',json.dumps(self.rt.snapshot()))

    def test_cancelling_confirmation_cannot_send(self):
        voice=jarvis.Voice(text_mode=True,ui=Mock())
        voice.text_mode=False
        def interrupted_answer(**kwargs):
            voice.interrupt.set()
            return 'yes'
        with patch.object(voice,'say'), patch.object(voice,'hear',side_effect=interrupted_answer):
            self.assertFalse(voice.confirm('Send it?'))
            self.assertFalse(voice.confirming)


if __name__=='__main__':
    unittest.main(verbosity=2)
