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

    def test_text_send_and_clear(self):
        client=Mock()
        client.chats.create.return_value.send_message.return_value.text='Offline reply'
        with patch('cloud.web_core.genai.Client',return_value=client), patch('cloud.ui.voice_composer') as composer:
            composer.return_value=None
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            composer.return_value={'id':'text-one','kind':'text','text':'Hello'}
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['messages'][-1]['text'],'Offline reply')
            self.assertFalse(composer.call_args.kwargs['autoplay'])
            at.run()
            client.chats.create.return_value.send_message.assert_called_once_with('Hello')
            composer.return_value=None
            at.button(key='clear').click().run()
            self.assertEqual(at.session_state['messages'],[])

    def test_full_pages_preserve_session(self):
        with patch('cloud.web_core.genai.Client'), patch('cloud.ui.voice_composer',return_value=None):
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            self.assertFalse(any('sidebar-brand' in item.value for item in at.sidebar.markdown))
            at.toggle(key='mic_enabled').set_value(True).run()
            for page,title in [('profile','Profile'),('messages','Messages'),('help','Help'),('settings','Settings')]:
                at.switch_page('views/'+page+'.py').run()
                self.assertFalse(at.exception)
                self.assertEqual(at.title[0].value,title)
                if page=='profile':
                    at.text_input(key='profile_name_input').set_value('Selim').run()
            at.switch_page('views/dashboard.py').run()
            self.assertTrue(at.toggle(key='mic_enabled').value)
            self.assertEqual(at.session_state['display_name'],'Selim')

    def test_recording_send_speaks_reply_without_review_or_duplicate_request(self):
        import base64
        client=Mock()
        client.models.generate_content.return_value.text='A recorded message'
        client.chats.create.return_value.send_message.return_value.text='Spoken answer'
        with patch('cloud.web_core.genai.Client',return_value=client), patch('cloud.ui.voice_composer') as composer:
            composer.return_value=None
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            at.toggle(key='mic_enabled').set_value(True).run()
            composer.return_value={'id':'voice-one','kind':'audio','audio':base64.b64encode(b'test-clip').decode(),'mime':'audio/webm;codecs=opus'}
            at.run()
            self.assertFalse(at.exception)
            client.models.generate_content.assert_called_once()
            client.chats.create.return_value.send_message.assert_called_once_with('A recorded message')
            self.assertTrue(composer.call_args.kwargs['autoplay'])
            self.assertEqual(composer.call_args.kwargs['reply'],'Spoken answer')
            self.assertTrue(composer.call_args.kwargs['reply_id'])
            self.assertTrue(any(item.label=='Voice reply transcript' for item in at.expander))
            self.assertNotIn('send_audio',[button.key for button in at.button])
            at.run()
            client.models.generate_content.assert_called_once()
            client.chats.create.return_value.send_message.assert_called_once()

    def test_bad_or_disabled_audio_never_calls_gemini(self):
        client=Mock()
        with patch('cloud.web_core.genai.Client',return_value=client), patch('cloud.ui.voice_composer') as composer:
            composer.return_value=None
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            composer.return_value={'id':'disabled','kind':'audio','audio':'AAAA','mime':'audio/webm'}
            at.run()
            self.assertIn('Enable Microphone',at.error[0].value)
            at.toggle(key='mic_enabled').set_value(True).run()
            composer.return_value={'id':'invalid','kind':'audio','audio':'not-base64','mime':'audio/webm'}
            at.run()
            self.assertTrue(at.error)
            client.models.generate_content.assert_not_called()

    def test_api_failure_has_no_spoken_success(self):
        client=Mock()
        client.chats.create.return_value.send_message.side_effect=RuntimeError('offline-test-key rejected')
        with patch('cloud.web_core.genai.Client',return_value=client), patch('cloud.ui.voice_composer') as composer:
            composer.return_value=None
            at=AppTest.from_file(str(APP),default_timeout=10)
            at.secrets={'GEMINI_API_KEY':'offline-test-key'}
            at.run()
            composer.return_value={'id':'fail','kind':'text','text':'Hello'}
            at.run()
            self.assertFalse(at.exception)
            self.assertIn('Gemini request failed',at.error[0].value)
            self.assertNotIn('offline-test-key',at.error[0].value)
            self.assertEqual(composer.call_args.kwargs['reply'],'')
            self.assertFalse(composer.call_args.kwargs['autoplay'])

    def test_busy_indicator_clears_after_failure(self):
        from cloud.ui import loading
        with patch('cloud.ui.st.empty') as placeholder:
            with self.assertRaises(RuntimeError):
                with loading('Thinking <test>'):
                    raise RuntimeError('Simulated provider failure')
            placeholder.return_value.empty.assert_called_once()
            markup=placeholder.return_value.markdown.call_args.args[0]
            self.assertIn('Thinking &lt;test&gt;',markup)
            self.assertIn('jarvis-loading-wordmark',markup)
            self.assertIn('jarvis-loading-dots',markup)
            self.assertEqual(markup.count('<i></i>'),3)
            self.assertIn('data:image/png;base64,',markup)


if __name__=='__main__':
    unittest.main(verbosity=2)
