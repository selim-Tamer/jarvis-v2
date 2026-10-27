# Jarvis Web: Streamlit localhost or Community Cloud

This is a separate web app. It supports typed chat, browser-recorded voice messages, current web search, timezone-aware time, email drafts, and optional browser speech output. It does not run the Windows microphone recorder, tray, app launcher, or background wake word. Email is draft-only here; sending remains in the Windows assistant, with spoken confirmation.

## Deploy using the screen you showed

Use these exact values:

| Field | Value |
| --- | --- |
| Repository | `selim-Tamer/jarvis-v2` |
| Branch | `main` |
| Main file path | `cloud/streamlit_app.py` |
| App URL | Your available name, such as `jarvis-v2-dpdp` |

Open **Advanced settings**, select **Python 3.14**, and add this in **Secrets**, replacing the placeholder with your real Gemini key:

```toml
GEMINI_API_KEY = "YOUR_REAL_KEY_HERE"
JARVIS_MODEL = "gemini-3.5-flash"
JARVIS_TIMEZONE = "Africa/Cairo"
```

Use a model available in your Gemini account. You can change `JARVIS_MODEL` later if Google reports that the configured model is unavailable. Do not add your Gmail password: the web app never sends email. Save settings and click **Deploy**. Keep app access private in Streamlit's sharing settings when using your personal API key.

Streamlit picks up `cloud/requirements.txt` beside the entry point, before the root Windows requirements. No Vite build, microphone device, tray library, or Windows audio package is required for this web deployment. See [Streamlit dependency-file precedence](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

If your deployment was already created with `jarvis.py`, create/redeploy it with the correct entry point above. Adding Streamlit to a requirements file does not make the desktop script a Streamlit app.

## Run as a localhost website

Open PowerShell:

```powershell
Set-Location 'C:\Users\user\Desktop\JARVIS v2.0\project\jarvis'
.\venv\Scripts\python.exe -m pip install --only-binary=:all: -r .\cloud\requirements.txt
.\venv\Scripts\python.exe -m streamlit run .\cloud\streamlit_app.py --server.address 127.0.0.1
```

Open **http://localhost:8501** and keep PowerShell open. The local web app reads your existing root `.env`. To use Streamlit Secrets locally instead, save the same TOML fields to `.streamlit/secrets.toml`; that private file is excluded from Git. Streamlit Secrets take priority over the local `.env`.

The original React/Windows app still starts with:

```powershell
.\venv\Scripts\python.exe .\launch.py
```

That version uses http://127.0.0.1:8000 and retains Windows functionality. The web and Windows interfaces do not share conversations or email drafts.

## Test

1. Open the page. With no key, expect setup instructions rather than a traceback. With a key, expect the chat box and voice-recording section.
2. Type `What time is it in my configured timezone?`. Expect a time reply, or a visible API error if the key/model is rejected.
3. Expand **Record a voice message**, record a short sentence, stop recording, and click **Send recording**. Allow browser microphone access when prompted. Your recording is sent to Gemini for transcription. Expect your transcript and a reply. HTTPS on Cloud or localhost is needed for browser microphone access.
4. Click **Read latest reply**, then **Stop speaking**. Playback uses your browser's speech engine; if unsupported or blocked, the text remains readable.
5. Ask `Draft an email to me@example.com with subject Test and body Hello`. Expect a downloadable draft labelled **nothing has been sent**. There is no send action or SMTP connection in this app.
6. Click **Clear conversation**. Expect an empty chat and no previous drafts. Each browser session has its own chat and drafts. They are not persisted across a new session, server restart, or cloud sleep/restart.

Run offline tests (no Gemini requests or emails):

```powershell
.\venv\Scripts\python.exe -m unittest -v cloud.test_web
```

The tests exercise both pure web logic and Streamlit's headless `AppTest` interface. Live Gemini access and actual browser recording still require your configured account and microphone permission.
