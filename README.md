# Jarvis v2.0: React interface, local Python assistant

## Install from GitHub on Windows

This repository contains a **Windows desktop assistant**. GitHub stores the code; the assistant runs on your laptop. It is not a Streamlit Cloud application.

Install Python 3.14, Node.js 24, and Git, then open PowerShell in the folder where you want to keep the project:

```powershell
git clone https://github.com/selim-Tamer/jarvis-v2.git
Set-Location .\jarvis-v2
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install --only-binary=:all: -r .\requirements.txt
npm.cmd ci --ignore-scripts
npm.cmd run build
Copy-Item .\.env.example .\.env
notepad .env
```

Fill your own settings in `.env`, save it, then run:

```powershell
.\venv\Scripts\python.exe .\launch.py
```

The repository is private, so cloning requires access through your GitHub account. Settings, browser profiles, contacts, reminders, recordings, logs, virtual environments, build output, and installed Node packages are excluded from Git. To configure contacts/apps, copy `contacts.example.json` to `contacts.json` or `apps.example.json` to `apps.json`, then edit your private copy.

For later code changes, check `git status`, commit the source files, and push to GitHub. Rebuild React with `npm.cmd run build` after pulling frontend changes. The sections below document the existing laptop installation and interactive tests.

Use **C:\Users\user\Desktop\JARVIS v2.0\project\jarvis**. Vite builds the React UI. `launch.py` serves that build, runs the existing Python assistant, and starts the Windows tray. Speech uses local faster-whisper and the isolated pyttsx3 speech worker; browser speech recognition is not used.

The original project is unchanged. The ZIP's previous source and build are backed up in `.before-fixes`. Its optional Supabase reminder server has been replaced with the Python core's local `reminders.json`. Do not run the old server from the backup.

## First launch

Python 3.14 dependencies and Node dependencies have been installed into this copy, and the frontend is built. No virtual-environment activation is needed. Quit the old Jarvis from its tray menu first, so both versions do not record at once.

Open PowerShell and paste:

```powershell
Set-Location 'C:\Users\user\Desktop\JARVIS v2.0\project\jarvis'
Copy-Item -LiteralPath 'C:\Users\user\Desktop\JARVIS\jarvis\.env' -Destination '.\.env'
.\venv\Scripts\python.exe .\launch.py
```

Copy `.env` only once; it contains your existing settings and credentials. The configuration file in `project\.env` from the ZIP is not used. Keep your real settings in **project\jarvis\.env**, beside `launch.py`. Never paste its contents into chat. To change a setting later:

```powershell
notepad .env
```

Expected: a dedicated Edge window and a tray icon appear. The UI shows startup steps, **Typing ready**, then Whisper/microphone progress and **Voice ready**. Edge is only the interface; Python uses your laptop's configured microphone directly. You do not need to grant browser microphone access. If Edge is not installed, the normal browser opens; hide-to-tray for that browser is unavailable, but the assistant/tray still run.

If port 8000 is occupied, stop that server before launching v2. A second v2 launch opens the running instance instead of starting another recorder. v2 uses a separate instance lock on port 47654.

## Test the fixes in order

### 1. Connection, configuration errors, and typing

Type `What time is it?` and press Enter while voice loads. You should receive a real reply or an explicit API error, never an assumed success. Enter sends; Shift+Enter adds a newline. Clear chat clears the visible conversation and resets model conversation before the next request. Requests are serialized; wait if the UI says one is in progress.

For a run with no microphone or speaker, quit v2 first, then:

```powershell
.\venv\Scripts\python.exe .\launch.py --text
```

Expected: text-only ready, typing works, and email cannot send because spoken confirmation is unavailable. To test a broken connection, stop the server with Ctrl+C; the interface must say it is disconnected and reconnect when you launch it again.

If `.env` is missing or the key is empty, the startup error appears in the window. No key or password should appear in logs. The frontend talks only to the local server; keys are never sent to React. External origins are rejected, and the local browser gets a per-process HTTP-only session cookie.

### 2. Local microphone, wake word, and speech

Quit text-only mode, then run normal mode:

```powershell
.\venv\Scripts\python.exe .\launch.py
```

Wait for **Voice ready**. Say `Jarvis, what time is it?` or your configured wake word. Also try the wake word alone, wait for `Yes?`, then ask your question. The transcript appears below the chat. It uses the core's Whisper prompt and fuzzy matching, rather than browser push-to-talk.

For microphone errors, quit v2 and run:

```powershell
.\venv\Scripts\python.exe .\mic_test.py
```

Expected: input device numbers and a moving level bar. Use your working device number as `JARVIS_MIC_DEVICE` in `.env`, or leave the setting empty for the Windows default. Model loading gets 180 seconds; other audio startup steps get 20 seconds. On failure, typing stays usable. Restart to retry voice.

To test the isolated speaker:

```powershell
'{"text":"Jarvis v2 speech test. One. Two. Three."}' | .\venv\Scripts\python.exe .\speech_worker.py
$LASTEXITCODE
```

Expected: speech and exit code 0. In the UI, request a short story, then press **Esc** or click the stop button while it speaks. The tray also has **Stop speaking**. A new typed request interrupts a final spoken reply. Voice interruption over the speaker is not implemented; use Esc/button/typing. Esc also cancels a pending email confirmation.

### 3. Spoken email confirmation

Leave email credentials in `.env`. To use your old contact names, copy your contacts once:

```powershell
Copy-Item -LiteralPath 'C:\Users\user\Desktop\JARVIS\jarvis\contacts.json' -Destination '.\contacts.json'
```

In normal mode, request an email **to your own address** with subject `Jarvis cancellation test`. After the recipient, subject and body are spoken, say **no**. Expected: no email sent. Repeat and remain silent: it must cancel. Text-only mode and failed speech cannot send. Typing `yes` during confirmation is rejected and never authorizes sending.

For an intentional real test, request a message to yourself with subject `Jarvis send test`. Say a clear **yes** after the complete read-back. Expected: one message in Gmail Sent. Pressing Esc, muting, or quitting during confirmation must cancel. These live tests require your action; automated checks mock SMTP and never send.

### 4. Tray, hide, quit, and shortcuts

Mute should update both the interface and Python recorder; typing still works. **Hide to tray** hides the dedicated Edge app window only after the tray is ready. Right-click the icon > **Open Jarvis** restores it. Closing the Edge window leaves the backend running; open it again from the tray. **Quit** from the window or tray stops the backend, recorder, and speech. It closes the owned Edge window; a normal browser tab may remain with a stopped message.

To create a desktop shortcut after testing:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\manage_shortcuts.ps1 -Action Desktop
```

Expected: a new **Jarvis v2.0** shortcut. It uses v2's `pythonw.exe` and the absolute path to `launch.py`. The original Jarvis shortcut is untouched.

To enable v2 at Windows sign-in:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\manage_shortcuts.ps1 -Action Enable
```

Expected: **Created:** followed by the v2 Startup shortcut path. It passes `--hidden`. Test by quitting v2, then running `.\venv\Scripts\python.exe .\launch.py --hidden` before signing out and in. If tray setup or assistant startup fails, a window opens with the error. Disable any old v1 autostart separately so both versions do not run together.

Inspect or disable only the v2 shortcuts:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\manage_shortcuts.ps1 -Action Check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\manage_shortcuts.ps1 -Action Disable
```

Autostart has not been enabled automatically. When launched without a console, output goes to `jarvis.log` in this folder.

### 5. Reminders, apps, and search

Try `Remind me in one minute to drink water.` Expect a saved due time, followed by a visible/spoken alert and tray notification when supported. Reminders persist locally in `reminders.json` and are checked even if the React window is closed. Jarvis must be running; it does not wake a sleeping laptop. Alerts can wait for the current request/speech to finish. This version uses local time, matching the original Python core; reminders from the replaced Supabase server are not imported.

Try `Open calculator.` and `Open notepad.` Those apps, Paint, and Explorer are allowlisted. For others, edit `apps.json`, mapping a name to an actual absolute `.exe` path. Shell commands are not accepted. Try `Search the web for today's weather in Cairo.` Expect a current reply or an explicit API/model error. Availability depends on your Gemini account and configured `JARVIS_MODEL`.

## Rebuild and automated checks

After editing React:

```powershell
npm.cmd run build
```

Expected: TypeScript checks and Vite production build pass. Restart Jarvis or reload its window to see changes. For frontend development, run `launch.py --no-browser` in one PowerShell window and `npm.cmd run dev` in a second; open `http://127.0.0.1:5173`. Vite proxies `/api` to Python on 8000. `npm.cmd run dev` alone does not start the assistant.

Run offline tests:

```powershell
.\venv\Scripts\python.exe -m unittest -v test_jarvis test_server
node --test test_frontend.mjs
```

Expected: tests pass with no Gemini requests, microphone recording, real email, or shortcut changes. They cover confirmation, cancellation, fake-success prevention, local HTTP access, streaming snapshots, worker serialization, and conversation reset.

For a fresh installation, create `venv` with Python 3.14, then install:

```powershell
.\venv\Scripts\python.exe -m pip install --only-binary=:all: -r .\requirements.txt
npm.cmd ci --ignore-scripts
npm.cmd run build
```

The packages in this setup were installed as compatible Windows Python 3.14 wheels. Node 24 was used for the build and frontend tests.
