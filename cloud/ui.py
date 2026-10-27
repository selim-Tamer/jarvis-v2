"""Shared Streamlit UI. Launch cloud/streamlit_app.py locally or on Streamlit Cloud."""
import hashlib
import base64
from contextlib import contextmanager
from html import escape
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import streamlit as st
from streamlit.components.v1 import declare_component
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from cloud.web_core import Settings, WebAssistant

_VOICE_COMPONENT = declare_component("jarvis_voice_composer", path=str(Path(__file__).with_name("voice_composer")))

def voice_composer(**kwargs):
    return _VOICE_COMPONENT(key="voice_composer", default=None, **kwargs)


def read_setting(name, default=""):
    # Read the desktop .env only on a local checkout; it is excluded from Git.
    local = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    try:
        value = st.secrets.get(name)
    except (FileNotFoundError, KeyError):
        value = None
    return str(value if value is not None else os.getenv(name, local.get(name) or default))


def render_reply(message):
    if message.get("voice"):
        st.caption("Spoken reply ready. Playback controls are in the message bar.")
        with st.expander("Voice reply transcript"):
            st.markdown(message["text"])
    else:
        st.markdown(message["text"])


def reset_recording():
    # Tell the browser recorder to release the microphone and discard the clip.
    st.session_state.recording_epoch = st.session_state.get("recording_epoch", 0) + 1
    st.session_state.pop("pending_audio", None)
    st.session_state.pop("audio_error", None)


def wordmark_markup():
    image = Path(__file__).with_name("assets") / "jarvis-logo.png"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return ('<span class="jarvis-loading-wordmark"><img alt="J.A.R.V.I.S." '
            'src="data:image/png;base64,' + encoded + '"></span>')


def loader_markup(message):
    # Liquid-metal loader adapted from Uiverse.io by chase2k25.
    return ('<div class="jarvis-loading" role="status" aria-live="polite">'
            '<div class="jarvis-liquid-loader" aria-hidden="true"><div class="jarvis-liquid-wrapper">'
            '<div class="jarvis-satellites"><span></span><span></span><span></span><span></span></div>'
            '<div class="jarvis-main-orb"></div></div><div class="jarvis-loading-centre">' + wordmark_markup() + '<span class="jarvis-loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>'
            '</div><p>' + escape(message) + '</p></div>')


@contextmanager
def loading(message):
    placeholder = st.empty()
    placeholder.markdown(loader_markup(message), unsafe_allow_html=True)
    try:
        yield
    finally:
        placeholder.empty()


def ai_core_markup():
    # Matching SVG geometry for the CSS-only Nawsome reference supplied by the user.
    return '''<div class="jarvis-core-stage"><div class="svg-frame"
        role="img" aria-label="Jarvis layered purple and blue ring visual">
      <svg viewBox="0 0 344 344" style="--i:0;--j:0" aria-hidden="true">
        <g id="out2" stroke="#9d8cff">
          <circle cx="172" cy="172" r="142" stroke-width="2"/>
          <circle cx="172" cy="172" r="116" stroke-width="5" stroke-dasharray="66 44 101 67 32 24 59 51 86 198" transform="rotate(-80 172 172)"/>
        </g>
      </svg>
      <svg viewBox="0 0 344 344" style="--i:1;--j:1" aria-hidden="true">
        <g id="out3" stroke="#6ba8ff" stroke-width="1.5">
          <circle cx="172" cy="172" r="98" stroke-dasharray="215 28 193 180" transform="rotate(39 172 172)"/>
        </g>
        <g id="inner1" stroke="#b9a8ff">
          <circle cx="172" cy="172" r="76" stroke-width="2" stroke-dasharray="132 103 91 152"/>
          <circle cx="172" cy="172" r="70" stroke-width="1" stroke-dasharray="151 111 65 113" transform="rotate(15 172 172)"/>
        </g>
      </svg>
      <svg viewBox="0 0 344 344" style="--i:2;--j:2" aria-hidden="true">
        <g id="inner3" stroke="#8b91ff" stroke-width="6">
          <circle cx="172" cy="172" r="79" stroke-dasharray="26 224 25 221" transform="rotate(-65 172 172)"/>
        </g>
        <g id="center">
          <circle cx="172" cy="172" r="36" stroke="#b9a8ff" stroke-width="2.5"/>
          <g id="center1" stroke="#6ba8ff" stroke-width="2" fill="none">
            <circle cx="172" cy="172" r="23" stroke-dasharray="111 34" transform="rotate(-20 172 172)"/>
          </g>
          <circle cx="172" cy="172" r="7" stroke="#9d8cff" stroke-width="1.5"/>
        </g>
      </svg>
    </div></div>'''


def logo_markup():
    image = Path(__file__).with_name("assets") / "jarvis-logo.png"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return ('<div class="jarvis-brand-header"><div class="jarvis-brand-logo">'
            '<img alt="J.A.R.V.I.S. logo" src="data:image/png;base64,' + encoded + '"></div></div>')


def current_settings():
    return Settings(api_key=read_setting("GEMINI_API_KEY"),
                    model=read_setting("JARVIS_MODEL", "gemini-3.5-flash"),
                    timezone=read_setting("JARVIS_TIMEZONE", "Africa/Cairo"))


def initialize_session():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("recording_epoch", 0)
    # Keep the permission setting across page changes, without keeping a recorder running.
    st.session_state.mic_enabled = st.session_state.get("mic_enabled", False)


def clear_conversation():
    previous = st.session_state.pop("agent", None)
    if previous:
        previous.close()
    st.session_state.messages = []
    st.session_state.pop("voice_composer", None)
    reset_recording()
    st.session_state.mic_enabled = False


def sidebar_navigation(pages, current_page):
    with st.sidebar:
        with st.container(key="nav_rail"):
            for page, title, icon in pages:
                with st.container(key="nav_active" if page is current_page else "nav_" + title.lower()):
                    st.page_link(page, label=title, icon=icon, width="stretch")
        st.button("Clear conversation", key="clear", on_click=clear_conversation)
        st.caption("Your private browser session")


def render_messages_page():
    st.title("Messages")
    st.caption("Your conversation in this browser session.")
    if not st.session_state.messages:
        st.info("No messages yet. Open Dashboard to start a conversation.")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message.get("error"):
                st.error(message["text"])
            else:
                st.markdown(message["text"])
    st.download_button("Export conversation", json.dumps(st.session_state.messages, indent=2),
                       file_name="jarvis-conversation.json", mime="application/json", key="export_chat")


def render_profile_page():
    st.title("Profile")
    st.caption("Personalise this browser session.")
    def save_name():
        st.session_state.display_name = st.session_state.profile_name_input.strip()
    st.text_input("Display name", value=st.session_state.get("display_name", ""),
                  key="profile_name_input", max_chars=40, on_change=save_name)
    st.info("Your name, conversation, and drafts belong to this browser session. They are not saved in an account.")


def render_settings_page():
    settings = current_settings()
    st.title("Settings")
    st.write("Model: " + settings.model)
    st.write("Timezone: " + settings.timezone)
    st.write("API key configured" if settings.api_key else "API key missing")
    st.info("Change these values in Streamlit Secrets, or the project's .env file when running locally. Your API key is never displayed.")
    st.caption("Enable Microphone, tap Record, and speak. Three seconds of silence finishes the clip; Send submits it and Jarvis replies aloud.")


def render_help_page():
    st.title("Help")
    st.markdown("""**Text messages:** type your request and press Enter or Send.

**Sound messages:** enable the Microphone switch, press the mic in the text bar to record,
then speak. Recording stops after three seconds of silence. Press Send in the message bar to send it. You can also press Send while talking to finish and send immediately.

**Speech output:** sound messages receive a spoken reply automatically. Use Replay reply or Stop speaking in the message bar. A transcript is available in a collapsed panel.

**Email:** this web app prepares drafts only. Sending with spoken confirmation remains in the Windows assistant.

Use the permanent sidebar to change pages. Your conversation stays available in Messages.""")


def render_workspace():
    settings = current_settings()
    fingerprint = hashlib.sha256((settings.api_key + settings.model + settings.timezone).encode()).hexdigest()
    st.markdown('<div class="jarvis-hero">' + ai_core_markup() + logo_markup() + '</div>', unsafe_allow_html=True)
    st.title("JARVIS · Web")
    name = st.session_state.get("display_name", "")
    st.caption((f"Welcome, {name}. " if name else "") + "Chat, record a voice message, search the web, or draft an email.")

    if not settings.api_key:
        st.warning("GEMINI_API_KEY is missing. In Streamlit Cloud open Advanced settings → Secrets, add your key, then save. For localhost, put it in the project's .env file.")
        st.code('GEMINI_API_KEY = "YOUR_KEY_HERE"\nJARVIS_MODEL = "gemini-3.5-flash"\nJARVIS_TIMEZONE = "Africa/Cairo"', language="toml")
        st.chat_input("Add your Gemini key to start", disabled=True)
        return

    if st.session_state.get("settings_id") != fingerprint:
        previous = st.session_state.pop("agent", None)
        if previous:
            previous.close()
        st.session_state.messages = []
        st.session_state.settings_id = fingerprint
    if "agent" not in st.session_state:
        try:
            st.session_state.agent = WebAssistant(settings)
        except Exception:
            st.error("Could not initialize Gemini. Check your model, API key, and timezone settings.")
            return
    agent = st.session_state.agent
    conversation = st.container(key="conversation")
    for message in st.session_state.messages:
        with conversation.chat_message(message["role"]):
            if message.get("error"):
                st.error(message["text"])
            else:
                render_reply(message)

    def respond(text, *, voice=False):
        st.session_state.messages.append({"role": "user", "text": text})
        with conversation.chat_message("user"):
            st.markdown(text)
        with conversation.chat_message("assistant"):
            try:
                with loading("Jarvis is thinking..."):
                    reply = agent.ask(text)
                result = {"role": "assistant", "text": reply, "voice": voice, "speech_id": uuid4().hex}
                render_reply(result)
                st.session_state.messages.append(result)
            except Exception as error:
                message = "Gemini request failed: " + agent.safe_error(error)
                st.error(message)
                st.session_state.messages.append({"role": "assistant", "text": message, "error": True})

    microphone_enabled = st.toggle("Microphone", value=False, key="mic_enabled", on_change=reset_recording)
    st.caption("Tap the mic, speak, then pause for three seconds. Press Send to submit your recording."
               if microphone_enabled else "Microphone off - enable the switch to record, or type below.")
    latest = st.session_state.messages[-1] if st.session_state.messages else {}
    spoken_reply = latest if latest.get("role") == "assistant" and not latest.get("error") else {}
    event = voice_composer(
        enabled=microphone_enabled, reset_token=st.session_state.recording_epoch,
        ack_id=st.session_state.get("composer_ack", ""),
        reply=spoken_reply.get("text", ""), reply_id=spoken_reply.get("speech_id", ""),
        autoplay=bool(spoken_reply.get("voice")),
    )
    if st.session_state.get("audio_error"):
        st.error(st.session_state.audio_error)
    if isinstance(event, dict) and event.get("id") and event["id"] != st.session_state.get("composer_ack"):
        # Acknowledge before calling Gemini, so reruns cannot send a clip twice.
        st.session_state.composer_ack = event["id"]
        st.session_state.pop("audio_error", None)
        try:
            if event.get("kind") == "audio":
                if not microphone_enabled:
                    raise ValueError("Enable Microphone before sending a recording.")
                encoded = event.get("audio", "")
                if not isinstance(encoded, str) or len(encoded) > 14 * 1024 * 1024:
                    raise ValueError("Record a shorter message under 10 MB.")
                clip = base64.b64decode(encoded, validate=True)
                mime = event.get("mime", "").split(";")[0]
                if mime not in {"audio/wav", "audio/webm", "audio/ogg", "audio/mp4"}:
                    raise ValueError("Unsupported recording format. Try Edge or Chrome.")
                with loading("Listening to your message..."):
                    transcript = agent.transcribe(clip, mime_type=mime)
                respond(transcript, voice=True)
            elif event.get("kind") == "text":
                text = event.get("text", "")
                if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                    raise ValueError("Type a message between 1 and 12000 characters.")
                respond(text)
            else:
                raise ValueError("Unknown message type. Please try again.")
        except Exception as error:
            st.session_state.audio_error = "Message failed: " + agent.safe_error(error)
        st.rerun()
    if agent.drafts:
        with st.expander("Email drafts — nothing has been sent"):
            for index, draft in enumerate(agent.drafts):
                st.text(f"To: {draft['to']}\nSubject: {draft['subject']}\n\n{draft['body']}")
                st.download_button("Download draft", data=f"To: {draft['to']}\nSubject: {draft['subject']}\n\n{draft['body']}",
                                   file_name=f"email-draft-{index+1}.txt", key=f"draft_{index}")
    st.caption("Conversation and drafts belong to this browser session and are cleared on a server restart or new session.")


def main():
    st.set_page_config(page_title="Jarvis Web", page_icon="🔵", layout="centered", initial_sidebar_state="expanded")
    css = Path(__file__).with_name("ui_styles.css").read_text(encoding="utf-8")
    st.markdown("<style>" + css + "</style>", unsafe_allow_html=True)
    initialize_session()
    views = Path(__file__).with_name("views")
    definitions = [
        ("dashboard", "Dashboard", ":material/dashboard:"),
        ("profile", "Profile", ":material/person:"),
        ("messages", "Messages", ":material/chat:"),
        ("help", "Help", ":material/help:"),
        ("settings", "Settings", ":material/settings:"),
    ]
    pages = [(st.Page(views / f"{slug}.py", title=title, icon=icon,
                      url_path=slug, default=slug == "dashboard"), title, icon)
             for slug, title, icon in definitions]
    navigation = st.navigation([page for page, _, _ in pages], position="hidden")
    sidebar_navigation(pages, navigation)
    with st.container(key="workspace"):
        navigation.run()


if __name__ == "__main__":
    main()
