"""Deploy this file to Streamlit Cloud, or run it locally with streamlit run."""
import hashlib
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


def main():
    st.set_page_config(page_title="Jarvis Web", page_icon="🔵", layout="centered")
    st.markdown("""<style>
    .stApp{background:#060a14;color:#e8edfb}
    .jarvis-orb{width:72px;height:72px;margin:12px auto 20px;border-radius:50%;background:radial-gradient(circle at 30% 25%,#8de2ff,#0891b2 65%,#123954);box-shadow:0 0 45px #0e749070}
    </style><div class="jarvis-orb" aria-hidden="true"></div>""", unsafe_allow_html=True)
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

    with st.sidebar:
        st.header("Jarvis Web")
        st.write("Model: " + settings.model)
        st.write("Timezone: " + settings.timezone)
        st.info("This is the browser version. Windows app launching, tray controls, background wake-word listening, and email sending remain in the desktop app.")
        if st.button("Clear conversation", key="clear"):
            previous = st.session_state.pop("agent", None)
            if previous:
                previous.close()
            st.session_state.messages = []
            st.session_state.recording_epoch += 1
            st.rerun()

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
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message.get("error"):
                st.error(message["text"])
            else:
                st.markdown(message["text"])

    def respond(text):
        st.session_state.messages.append({"role": "user", "text": text})
        with st.chat_message("user"):
            st.markdown(text)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Jarvis is thinking..."):
                    reply = agent.ask(text)
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "text": reply})
            except Exception as error:
                message = "Gemini request failed: " + agent.safe_error(error)
                st.error(message)
                st.session_state.messages.append({"role": "assistant", "text": message, "error": True})

    with st.expander("Record a voice message"):
        st.caption("Record, stop, then click Send recording. Your recording is sent to Gemini for transcription. No wake word is required.")
        recording = st.audio_input("Voice message", key=f"voice_{st.session_state.recording_epoch}", sample_rate=16000)
        if st.button("Send recording", disabled=recording is None, key="send_audio"):
            try:
                with st.spinner("Transcribing recording..."):
                    transcript = agent.transcribe(recording.getvalue())
            except Exception as error:
                st.error("Transcription failed: " + agent.safe_error(error))
            else:
                respond(transcript)
                st.session_state.recording_epoch += 1
                st.rerun()

    prompt = st.chat_input("Ask Jarvis", max_chars=12000)
    if prompt:
        respond(prompt)
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


if __name__ == "__main__":
    main()
