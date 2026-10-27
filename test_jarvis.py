"""Offline regression checks. Never contacts Gemini or sends email."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import jarvis


class Checks(unittest.TestCase):
    def voice(self):
        return jarvis.Voice(text_mode=True, ui=Mock())

    def test_wake_word(self):
        with patch.object(jarvis, 'WAKE_WORD', 'jarvis'):
            self.assertEqual(jarvis.wake_command('Jarvis, tell me the time'), 'tell me the time')
            self.assertEqual(jarvis.wake_command('Hey Jervis, hello'), 'hello')
            self.assertEqual(jarvis.wake_command('Jarves'), '')
            self.assertIsNone(jarvis.wake_command('jarvisville open mail'))
            self.assertIsNone(jarvis.wake_command('I like harvest time'))

    def test_credentials_redacted(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'fake-key', 'EMAIL_APP_PASSWORD': 'fake-password'}):
            self.assertEqual(jarvis.safe_error(Exception('fake-key fake-password')), '[redacted] [redacted]')

    def test_loading_does_not_block_typing(self):
        voice = self.voice()
        gate = threading.Event()
        with patch.object(voice, '_init_audio', side_effect=lambda: gate.wait(2)):
            voice.start_audio()
            voice.typed.put('hello')
            self.assertEqual(voice.hear(), 'hello')
            self.assertTrue(voice.last_typed)
            voice.stage_started = time.monotonic() - 21
            voice.check_audio()
            self.assertTrue(voice.audio_failed)
            self.assertTrue(voice.text_mode)
            gate.set()

    def test_audio_ready(self):
        voice = self.voice()
        voice.audio_started = time.monotonic()
        voice.audio_result.put(None)
        voice.check_audio()
        self.assertFalse(voice.text_mode)

    def test_typed_confirmation_never_sends(self):
        voice = self.voice()
        voice.typed.put('yes')
        tool = jarvis.make_tools(Mock(), voice)[0]
        with patch.dict(os.environ, {'EMAIL_ADDRESS': 'fake@example.com', 'EMAIL_APP_PASSWORD': 'fake'}), patch.object(jarvis, 'smtp_send') as send:
            self.assertIn('NOT sent', tool('friend@example.com', 'Test', 'Hello'))
            send.assert_not_called()

    def test_spoken_confirmation(self):
        for answer, expected in [('yes', True), ('yes no', False), ('not yet', False), ('', False), ('yesterday', False)]:
            voice = self.voice()
            voice.text_mode = False
            with patch.object(voice, 'say'), patch.object(voice, 'hear', return_value=answer):
                self.assertEqual(voice.confirm('Send it?'), expected)
        voice = self.voice()
        voice.text_mode = False
        def typed_answer(**kwargs):
            voice.last_typed = True
            return 'yes'
        with patch.object(voice, 'say'), patch.object(voice, 'hear', side_effect=typed_answer):
            self.assertFalse(voice.confirm('Send it?'))

    def test_email_only_after_confirmation(self):
        voice = self.voice()
        tool = jarvis.make_tools(Mock(), voice)[0]
        with patch.dict(os.environ, {'EMAIL_ADDRESS': 'fake@example.com', 'EMAIL_APP_PASSWORD': 'fake'}), patch.object(jarvis, 'smtp_send') as send:
            with patch.object(voice, 'confirm', return_value=False):
                tool('friend@example.com', 'Test', 'Hello')
                send.assert_not_called()
            with patch.object(voice, 'confirm', return_value=True):
                tool('friend@example.com', 'Test', 'Hello')
                send.assert_called_once_with('friend@example.com', 'Test', 'Hello')

    def test_reminders_survive_restart_and_fire_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.json'
            store = jarvis.ReminderStore(path)
            store.add(1, 'Drink water')
            self.assertEqual(len(jarvis.ReminderStore(path).items), 1)
            data = json.loads(path.read_text())
            data[0]['due'] = '2000-01-01T00:00:00'
            path.write_text(json.dumps(data))
            store = jarvis.ReminderStore(path)
            self.assertEqual(store.take_due()[0]['text'], 'Drink water')
            self.assertEqual(jarvis.ReminderStore(path).take_due(), [])

    def test_apps_do_not_accept_shell_commands(self):
        voice = self.voice()
        tool = next(t for t in jarvis.make_tools(Mock(), voice) if t.__name__ == 'open_app')
        with patch.object(jarvis.subprocess, 'Popen') as start:
            self.assertIn('not configured', tool('notepad & calc'))
            start.assert_not_called()
            tool('notepad')
            start.assert_called_once_with(['notepad.exe'], shell=False)

    def test_speech_failure_and_interrupt(self):
        voice = self.voice()
        voice.text_mode = False
        failed = Mock()
        failed.poll.return_value = 1
        failed.returncode = 1
        with patch.object(jarvis.subprocess, 'Popen', return_value=failed):
            voice.say('hello')
            self.assertFalse(voice.speech_ok)
        voice.speech_ok = True
        voice.typed.put('next question')
        speaking = Mock()
        speaking.poll.side_effect = [None, 0]
        speaking.returncode = -1
        with patch.object(jarvis.subprocess, 'Popen', return_value=speaking):
            voice.say('long reply')
            speaking.terminate.assert_called_once()
            self.assertTrue(voice.speech_ok)


if __name__ == '__main__':
    unittest.main(verbosity=2)
