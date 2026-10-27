"""Deploy this file to Streamlit Cloud, or run it locally with streamlit run."""
import hashlib
import base64
from contextlib import contextmanager
from html import escape
import json
import os
from pathlib import Path
import sys

import streamlit as st
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from cloud.web_core import Settings, WebAssistant


def read_setting(name, default=""):
    # Read the desktop .env only on a local checkout; it is excluded from Git.
    local = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    try:
        value = st.secrets.get(name)
    except (FileNotFoundError, KeyError):
        value = None
    return str(value if value is not None else os.getenv(name, local.get(name) or default))


def speech_controls(text):
    # JSON escaping prevents model output from closing this trusted script tag.
    payload = json.dumps(text).replace("<", "\\u003c")
    st.iframe("""<style>body{margin:0;color:#cbd5e1;font:14px sans-serif}
    button{background:#14253c;color:#e8edfb;border:1px solid #38bdf8;border-radius:8px;padding:9px;cursor:pointer}</style>
    <button id="read">Read latest reply</button> <button id="stop">Stop speaking</button>
    <span id="notice" role="status"></span><script>
    const text=""" + payload + """;
    document.getElementById('read').onclick=()=>{
      if(!('speechSynthesis' in window)){document.getElementById('notice').textContent='Speech unavailable in this browser.';return;}
      speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);
      utterance.onerror=()=>{document.getElementById('notice').textContent='Browser speech failed. The reply remains above.';};
      speechSynthesis.speak(utterance);
    };
    document.getElementById('stop').onclick=()=>{if('speechSynthesis' in window)speechSynthesis.cancel();};
    window.addEventListener('keydown',event=>{if(event.key==='Escape'&&'speechSynthesis' in window)speechSynthesis.cancel();});
    window.addEventListener('unload',()=>{if('speechSynthesis' in window)speechSynthesis.cancel();});
    </script>""", height=58)


def reset_recording():
    # A new widget key discards any previous clip, including when disabling the mic.
    st.session_state.recording_epoch = st.session_state.get("recording_epoch", 0) + 1
    st.session_state.pop("pending_audio", None)
    st.session_state.pop("audio_error", None)


def loader_markup(message):
    # Liquid-metal loader adapted from Uiverse.io by chase2k25.
    return ('<div class="jarvis-loading" role="status" aria-live="polite">'
            '<div class="jarvis-liquid-loader" aria-hidden="true"><div class="jarvis-liquid-wrapper">'
            '<div class="jarvis-satellites"><span></span><span></span><span></span><span></span></div>'
            '<div class="jarvis-main-orb"></div></div><span class="jarvis-loader-text">JARVIS</span>'
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
        role="img" aria-label="Jarvis layered cyan and yellow ring visual">
      <svg viewBox="0 0 344 344" style="--i:0;--j:0" aria-hidden="true">
        <g id="out2" stroke="#31d9e7">
          <circle cx="172" cy="172" r="142" stroke-width="2"/>
          <circle cx="172" cy="172" r="116" stroke-width="5" stroke-dasharray="66 44 101 67 32 24 59 51 86 198" transform="rotate(-80 172 172)"/>
        </g>
      </svg>
      <svg viewBox="0 0 344 344" style="--i:1;--j:1" aria-hidden="true">
        <g id="out3" stroke="#d8d16e" stroke-width="1.5">
          <circle cx="172" cy="172" r="98" stroke-dasharray="215 28 193 180" transform="rotate(39 172 172)"/>
        </g>
        <g id="inner1" stroke="#31d9e7">
          <circle cx="172" cy="172" r="76" stroke-width="2" stroke-dasharray="132 103 91 152"/>
          <circle cx="172" cy="172" r="70" stroke-width="1" stroke-dasharray="151 111 65 113" transform="rotate(15 172 172)"/>
        </g>
      </svg>
      <svg viewBox="0 0 344 344" style="--i:2;--j:2" aria-hidden="true">
        <g id="inner3" stroke="#31d9e7" stroke-width="6">
          <circle cx="172" cy="172" r="79" stroke-dasharray="26 224 25 221" transform="rotate(-65 172 172)"/>
        </g>
        <g id="center">
          <circle cx="172" cy="172" r="36" stroke="#31d9e7" stroke-width="2.5"/>
          <g id="center1" stroke="#d8d16e" stroke-width="2" fill="none">
            <circle cx="172" cy="172" r="23" stroke-dasharray="111 34" transform="rotate(-20 172 172)"/>
          </g>
          <circle cx="172" cy="172" r="7" stroke="#318894" stroke-width="1.5"/>
        </g>
      </svg>
    </div></div>'''


def logo_markup():
    image = Path(__file__).with_name("assets") / "jarvis-logo.png"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return ('<div class="jarvis-brand-header"><div class="jarvis-brand-logo">'
            '<img alt="J.A.R.V.I.S. logo" src="data:image/png;base64,' + encoded + '"></div></div>')


def sidebar_navigation(settings):
    with st.sidebar:
        st.header("Jarvis")
        rail, panel = st.columns([1, 2.5], gap="small")
        with rail:
            with st.container(key="nav_rail"):
                section = st.radio("Navigation", ["Dashboard", "Profile", "Messages", "Help", "Settings"],
                                   key="navigation", label_visibility="collapsed")
        with panel:
            with st.container(key="nav_panel"):
                st.subheader(section)
                if section == "Dashboard":
                    st.write(f"{len(st.session_state.messages)} conversation messages")
                    st.write("Microphone enabled" if st.session_state.get("mic_enabled", False) else "Microphone off")
                    st.caption("Use the main panel to type or record a message.")
                elif section == "Profile":
                    st.write("Your browser session")
                    st.caption("Conversation and drafts belong to this session. This web app does not create a profile or store your chat in an account.")
                elif section == "Messages":
                    st.write(f"{len(st.session_state.messages)} messages")
                    st.download_button("Export conversation", json.dumps(st.session_state.messages, indent=2),
                                       file_name="jarvis-conversation.json", mime="application/json", key="export_chat")
                elif section == "Help":
                    st.write("Type and press Enter to chat. Enable the microphone before recording.")
                    st.caption("Email is draft-only here. Windows app launching, the tray, and confirmed email sending remain in the desktop version.")
                else:
                    st.write("Model: " + settings.model)
                    st.write("Timezone: " + settings.timezone)
                    st.caption("Change these in Streamlit Secrets, or .env when running locally. Your API key is never displayed.")
        if st.button("Clear conversation", key="clear"):
            previous = st.session_state.pop("agent", None)
            if previous:
                previous.close()
            st.session_state.messages = []
            reset_recording()
            st.session_state.mic_enabled = False
            st.rerun()


def render_workspace():
    st.markdown('''<div class="jarvis-window-bar" aria-hidden="true">
        <div class="jarvis-window-dots"><span></span><span></span><span></span></div>
        <div class="jarvis-window-chevrons"><span>‹</span><span>›</span></div>
        <div class="jarvis-window-address">Jarvis assistant</div>
        </div>''', unsafe_allow_html=True)
    st.markdown(logo_markup(), unsafe_allow_html=True)
    st.markdown(ai_core_markup(), unsafe_allow_html=True)
    st.title("JARVIS · Web")
    st.caption("Chat, record a voice message, search the web, or draft an email.")
    settings = Settings(api_key=read_setting("GEMINI_API_KEY"),
                        model=read_setting("JARVIS_MODEL", "gemini-3.5-flash"),
                        timezone=read_setting("JARVIS_TIMEZONE", "Africa/Cairo"))
    fingerprint = hashlib.sha256((settings.api_key + settings.model + settings.timezone).encode()).hexdigest()
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "recording_epoch" not in st.session_state:
        st.session_state.recording_epoch = 0

    sidebar_navigation(settings)

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
                st.markdown(message["text"])

    def respond(text):
        st.session_state.messages.append({"role": "user", "text": text})
        with conversation.chat_message("user"):
            st.markdown(text)
        with conversation.chat_message("assistant"):
            try:
                with loading("Jarvis is thinking..."):
                    reply = agent.ask(text)
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "text": reply})
            except Exception as error:
                message = "Gemini request failed: " + agent.safe_error(error)
                st.error(message)
                st.session_state.messages.append({"role": "assistant", "text": message, "error": True})

    microphone_enabled = st.toggle("Microphone", value=False, key="mic_enabled", on_change=reset_recording)
    st.caption("Microphone enabled — press the mic beside the message field to record, then press it again to stop."
               if microphone_enabled else "Microphone off — enable the switch to record, or type below.")
    with st.container(key="composer"):
        mic_column, input_column = st.columns([1, 10], gap="small", vertical_alignment="center")
        with mic_column:
            with st.container(key="composer_recorder"):
                recording = st.audio_input("Record a sound message", key=f"voice_{st.session_state.recording_epoch}",
                                           sample_rate=16000, disabled=not microphone_enabled,
                                           label_visibility="collapsed")
        with input_column:
            prompt = st.chat_input("Ask Jarvis…", max_chars=12000, key="prompt")
    if recording is not None and microphone_enabled:
        clip = recording.getvalue()
        if len(clip) <= 10 * 1024 * 1024:
            st.session_state.pending_audio = clip
            st.session_state.pop("audio_error", None)
        else:
            st.session_state.pop("pending_audio", None)
            st.session_state.audio_error = "Record a shorter sound message under 10 MB."
        st.session_state.recording_epoch += 1
        st.rerun()
    if st.session_state.get("audio_error"):
        st.error(st.session_state.audio_error)
    if st.session_state.get("pending_audio") and microphone_enabled:
        with st.container(key="recording_preview"):
            st.caption("Sound message ready. Review it before sending. Sending transcribes the recording with Gemini.")
            st.audio(st.session_state.pending_audio, format="audio/wav")
            send_column, discard_column = st.columns(2)
            with send_column:
                send_audio = st.button("Send recording", key="send_audio")
            with discard_column:
                discard_audio = st.button("Discard recording", key="discard_audio")
            if discard_audio:
                reset_recording()
                st.rerun()
            if send_audio:
                try:
                    with loading("Transcribing recording..."):
                        transcript = agent.transcribe(st.session_state.pending_audio)
                except Exception as error:
                    st.error("Transcription failed: " + agent.safe_error(error))
                else:
                    reset_recording()
                    respond(transcript)
                    st.rerun()
    if prompt:
        respond(prompt)
        st.rerun()
    if (st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant"
            and not st.session_state.messages[-1].get("error")):
        speech_controls(st.session_state.messages[-1]["text"])
    if agent.drafts:
        with st.expander("Email drafts — nothing has been sent"):
            for index, draft in enumerate(agent.drafts):
                st.text(f"To: {draft['to']}\nSubject: {draft['subject']}\n\n{draft['body']}")
                st.download_button("Download draft", data=f"To: {draft['to']}\nSubject: {draft['subject']}\n\n{draft['body']}",
                                   file_name=f"email-draft-{index+1}.txt", key=f"draft_{index}")
    st.caption("Conversation and drafts belong to this browser session and are cleared on a server restart or new session.")


def main():
    st.set_page_config(page_title="Jarvis Web", page_icon="🔵", layout="centered")
    css = Path(__file__).with_name("ui_styles.css").read_text(encoding="utf-8")
    st.markdown("<style>" + css + "</style>", unsafe_allow_html=True)
    with st.container(key="workspace"):
        render_workspace()


if __name__ == "__main__":
    main()
