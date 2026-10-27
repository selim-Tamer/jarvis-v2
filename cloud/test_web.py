"""Web regressions. All provider responses are mocked; no API calls or SMTP."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest
from cloud.web_core import Settings, WebAssistant

APP=Path(__file__).parent/'streamlit_app.py'


class WebChecks(unittest.TestCase):
    def assistant(self):
        client=Mock()
        client.chats.create.return_value.send_message.return_value.text='Offline reply'
        return WebAssistant(Settings('fake-key'),client=client)

    def test_empty_responses_never_become_success(self):
        agent=self.assistant()
        agent.chat.send_message.return_value.text=''
        with self.assertRaises(RuntimeError):
            agent.ask('hello')

    def test_drafts_are_only_drafts_and_are_session_local(self):
        first=self.assistant()
        second=self.assistant()
        result=json.loads(first.draft_email('me@example.com','Test','Hello'))
        self.assertEqual(result['status'],'draft_only_NOT_SENT')
        self.assertEqual(len(first.drafts),1)
        self.assertEqual(second.drafts,[])
        self.assertFalse(hasattr(first,'send_email'))

    def test_audio_has_limits_and_no_empty_transcript(self):
        agent=self.assistant()
        with self.assertRaises(ValueError):
            agent.transcribe(b'')
        with self.assertRaises(ValueError):
            agent.transcribe(b'x'*(10*1024*1024+1))
        agent.client.models.generate_content.return_value.text=''
        with self.assertRaises(ValueError):
            agent.transcribe(b'fake-audio')
        agent.client.models.generate_content.return_value.text='Hello Jarvis'
        self.assertEqual(agent.transcribe(b'fake-audio'),'Hello Jarvis')

    def test_errors_redact_key_and_settings_repr(self):
        agent=self.assistant()
        self.assertNotIn('fake-key',agent.safe_error(Exception('API key fake-key rejected')))
        self.assertNotIn('fake-key',repr(agent.settings))

    def test_tool_schema_does_not_include_windows_or_send_tools(self):
        agent=self.assistant()
        config=agent.client.chats.create.call_args.kwargs['config']
        self.assertEqual({tool.__name__ for tool in config.tools},
                         {'search_web','get_current_datetime','draft_email'})

    def test_app_missing_key_shows_setup_without_crashing(self):
        at=AppTest.from_file(str(APP),default_timeout=10)
        at.secrets={'GEMINI_API_KEY':''}
        at.run()
        self.assertFalse(at.exception)
        self.assertIn('GEMINI_API_KEY is missing',at.warning[0].value)
        self.assertTrue(at.chat_input[0].disabled)

    def test_app_chat_and_clear_do_not_call_real_api(self):
        client=Mock()
        client.chats.create.return_value.send_message.return_value.text='Offline reply'
        with patch('cloud.web_core.genai.Client',return_value=client):
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            self.assertFalse(at.exception)
            at.radio(key='navigation').set_value('Settings').run()
            self.assertFalse(at.exception)
            self.assertTrue(any('Model:' in item.value for item in at.markdown))
            at.chat_input[0].set_value('Hello web app').run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['messages'][-1]['text'],'Offline reply')
            client.chats.create.return_value.send_message.assert_called_once_with('Hello web app')
            at.button(key='clear').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['messages'],[])

    def test_api_failure_is_visible_and_redacted(self):
        client=Mock()
        client.chats.create.return_value.send_message.side_effect=RuntimeError('offline-test-key rejected')
        with patch('cloud.web_core.genai.Client',return_value=client):
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            at.chat_input[0].set_value('Hello').run()
            self.assertFalse(at.exception)
            self.assertIn('Gemini request failed',at.error[0].value)
            self.assertNotIn('offline-test-key',at.error[0].value)
            at.run()
            self.assertIn('Gemini request failed',at.error[0].value)

    def test_speech_controls_do_not_execute_model_markup(self):
        from cloud.streamlit_app import speech_controls
        with patch('cloud.streamlit_app.st.iframe') as embed:
            speech_controls('</script><script>alert("unsafe")</script>')
            source=embed.call_args.args[0]
            self.assertNotIn('</script><script>alert',source)
            self.assertIn('\\u003c/script>',source)

    def test_microphone_toggle_gates_recording_and_resets_old_clip(self):
        client=Mock()
        with patch('cloud.web_core.genai.Client',return_value=client):
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            self.assertFalse(at.exception)
            self.assertFalse(at.toggle(key='mic_enabled').value)
            self.assertEqual(len(at.toggle),1)
            self.assertTrue(at.audio_input[0].disabled)
            self.assertNotIn('send_audio',[button.key for button in at.button])
            initial=at.session_state['recording_epoch']
            at.toggle(key='mic_enabled').set_value(True).run()
            self.assertFalse(at.exception)
            self.assertFalse(at.audio_input[0].disabled)
            self.assertGreater(at.session_state['recording_epoch'],initial)
            enabled_epoch=at.session_state['recording_epoch']
            at.toggle(key='mic_enabled').set_value(False).run()
            self.assertTrue(at.audio_input[0].disabled)
            self.assertNotIn('send_audio',[button.key for button in at.button])
            self.assertGreater(at.session_state['recording_epoch'],enabled_epoch)
            client.models.generate_content.assert_not_called()

    def test_sound_message_waits_for_review_then_sends_once(self):
        import io
        import wave
        audio=io.BytesIO()
        with wave.open(audio,'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\0\0'*1600)
        clip=audio.getvalue()
        client=Mock()
        client.models.generate_content.return_value.text='A recorded sound message'
        client.chats.create.return_value.send_message.return_value.text='Sound received'
        with patch('cloud.web_core.genai.Client',return_value=client):
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            at.toggle(key='mic_enabled').set_value(True).run()
            at.audio_input[0].set_value(('message.wav',clip,'audio/wav')).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['pending_audio'],clip)
            client.models.generate_content.assert_not_called()
            at.button(key='send_audio').click().run()
            self.assertFalse(at.exception)
            client.models.generate_content.assert_called_once()
            client.chats.create.return_value.send_message.assert_called_once_with('A recorded sound message')
            self.assertNotIn('pending_audio',at.session_state)
            at.audio_input[0].set_value(('message.wav',clip,'audio/wav')).run()
            at.toggle(key='mic_enabled').set_value(False).run()
            self.assertNotIn('pending_audio',at.session_state)

    def test_busy_indicator_clears_after_failure(self):
        from cloud.streamlit_app import loading
        with patch('cloud.streamlit_app.st.empty') as placeholder:
            with self.assertRaises(RuntimeError):
                with loading('Thinking <test>'):
                    raise RuntimeError('Simulated provider failure')
            placeholder.return_value.empty.assert_called_once()
            markup=placeholder.return_value.markdown.call_args.args[0]
            self.assertIn('Thinking &lt;test&gt;',markup)


if __name__=='__main__':
    unittest.main(verbosity=2)
