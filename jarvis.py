#!/usr/bin/env python3
"""Jarvis core: listens, thinks (Gemini), acts and answers out loud.

Use it from a terminal:   python jarvis.py          (voice)
                          python jarvis.py --text   (typing)
Or use the desktop app:   python jarvis_ui.py       (window + tray + background)
"""
import argparse
import difflib
import json
import os
import queue
import re
import smtplib
import ssl
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

MODEL = os.getenv("JARVIS_MODEL", "gemini-3.5-flash")
WAKE_WORD = os.getenv("JARVIS_WAKE_WORD", "jarvis").lower()
WHISPER_SIZE = os.getenv("WHISPER_MODEL", "small")
USER_NAME = os.getenv("JARVIS_USER_NAME", "")
SAMPLE_RATE = 16000

YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "send", "confirm", "ok", "okay", "correct"}
NO_WORDS = {"no", "nope", "don't", "dont", "cancel", "stop", "wait", "not"}
QUIT_PHRASES = {"quit", "exit", "goodbye", "bye", "shut down", "stop listening"}


def safe_error(error):
    """Redact credentials even when a third-party exception includes a URL."""
    text = str(error)
    for key in ("GEMINI_API_KEY", "EMAIL_APP_PASSWORD"):
        secret = os.getenv(key, "")
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def wake_command(text):
    """Match whole words; accept a close spelling only at the start."""
    words = list(re.finditer(r"[\w']+", text.lower()))
    for i, word in enumerate(words):
        token = word.group()
        exact = token == WAKE_WORD
        near_start = i == 0 or (i == 1 and words[0].group() in {"hey", "hi", "okay", "ok"})
        fuzzy = (near_start and len(token) >= 5 and len(WAKE_WORD) >= 5
                 and difflib.SequenceMatcher(None, token, WAKE_WORD).ratio() >= 0.80)
        if exact or fuzzy:
            return text[word.end():].strip(" ,.!?")
    return None


class ReminderStore:
    """Local reminders persist across restarts; due items run while Jarvis is open."""
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else HERE / "reminders.json"
        self.items = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    raise ValueError("Expected a list")
                for item in data:
                    datetime.fromisoformat(item["due"])
                    if not isinstance(item["text"], str):
                        raise ValueError("Expected reminder text")
                self.items = data
            except (ValueError, KeyError, TypeError):
                raise ValueError("reminders.json is invalid. Rename it to reminders.backup.json and restart.") from None

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, minutes, text):
        if not 0 < minutes <= 525600 or not text.strip():
            return "Use a reminder between 0 and 525600 minutes with a message."
        due = datetime.now() + timedelta(minutes=minutes)
        self.items.append({"due": due.isoformat(), "text": text.strip()})
        self.save()
        return f"Reminder saved for {due:%Y-%m-%d %H:%M:%S}. Jarvis must be running to alert you."

    def take_due(self):
        now = datetime.now()
        due = [item for item in self.items if datetime.fromisoformat(item["due"]) <= now]
        if due:
            self.items = [item for item in self.items if item not in due]
            self.save()
        return due


# --------------------------------------------------------------------------
# Console output (the desktop app swaps this for a window)
# --------------------------------------------------------------------------
class ConsoleUI:
    """Anything with state(name) and log(who, text) can be used instead."""

    def state(self, name):
        if name == "hearing":
            print("(hearing you...)")

    def log(self, who, text):
        text = safe_error(text)
        if who == "jarvis":
            print(f"Jarvis: {text}")
        elif who == "heard":
            print(f"You: {text}")
        elif who in ("system", "note"):
            print(f"({text})")
        # who == "user" is already visible (typed, or printed as 'heard')


# --------------------------------------------------------------------------
# Voice: microphone in, speaker out
# --------------------------------------------------------------------------
class Voice:
    def __init__(self, text_mode=False, ui=None, typed=None, stop=None, muted=None,
                 console=False, interrupt=None):
        self.text_mode = text_mode      # True = no microphone/speaker, text only
        self.console = console          # True = read typed input from the terminal
        self.ui = ui if ui is not None else ConsoleUI()
        self.typed = typed if typed is not None else queue.Queue()
        self.stop = stop if stop is not None else threading.Event()
        self.muted = muted if muted is not None else threading.Event()
        self.last_typed = False
        self.interrupt = interrupt if interrupt is not None else threading.Event()
        self.speech_ok = True
        self.confirming = False
        self.audio_result = queue.Queue()
        self.audio_started = None
        self.audio_failed = False
        self.audio_ready = False
        self.capture_cancel = threading.Event()
        self.stage = "not started"
        self.stage_started = time.monotonic()
        self.reminders = ReminderStore()
        if text_mode:
            return

        self._init_audio()

    def progress(self, text):
        self.stage = text
        self.stage_started = time.monotonic()
        self.ui.log("system", text)

    def _init_audio(self):
        self.progress("Voice step 1/3: importing microphone and Whisper packages...")

        import numpy as np
        import sounddevice as sd
        from faster_whisper import WhisperModel

        self.np = np
        self.sd = sd
        dev = os.getenv("JARVIS_MIC_DEVICE", "").strip()
        self.device = int(dev) if dev.isdigit() else (dev or None)

        self.progress(f"Voice step 2/3: loading Whisper '{WHISPER_SIZE}' (first run downloads it)...")
        self.stt = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
        self.progress("Voice step 3/3: opening microphone and calibrating; stay quiet...")
        self.threshold = self._calibrate()
        self.audio_ready = True

    def start_audio(self):
        """Initialize independently so typed requests work during downloads."""
        self.audio_started = time.monotonic()
        def initialize():
            try:
                self._init_audio()
                self.audio_result.put(None)
            except Exception as error:
                self.audio_result.put(safe_error(error))
        threading.Thread(target=initialize, daemon=True, name="voice-startup").start()

    def check_audio(self):
        if self.audio_started is None or self.audio_failed or not self.text_mode:
            return
        try:
            error = self.audio_result.get_nowait()
        except queue.Empty:
            elapsed = time.monotonic() - self.stage_started
            limit = 180 if "2/3" in self.stage else 20
            if elapsed < limit:
                return
            error = f"Timed out after {limit}s: {self.stage} Restart to retry voice."
        if error:
            self.audio_failed = True
            self.audio_ready = False
            self.ui.log("system", f"Voice unavailable: {error} Typing still works. Run mic_test.py to check the microphone.")
            self.ui.state("textonly")
        else:
            self.text_mode = False
            self.ui.log("system", f"Voice ready. Say '{WAKE_WORD}'.")
            self.ui.state("listening")

    # ---- speaking ----
    def say(self, text):
        self.ui.log("jarvis", text)
        if (not self.text_mode or self.audio_started is not None) and self.speech_ok:
            self.ui.state("speaking")
            self.interrupt.clear()
            process = None
            try:
                # SAPI/COM lives on the main thread of a fresh child process.
                process = subprocess.Popen(
                    [sys.executable, str(HERE / "speech_worker.py")],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                process.stdin.write(json.dumps({"text": text}).encode("utf-8"))
                process.stdin.close()
                deadline = time.monotonic() + min(180, max(20, len(text.split()) * 0.7 + 10))
                while process.poll() is None:
                    if self.stop.is_set() or self.interrupt.is_set() or not self.typed.empty():
                        process.terminate()
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Speech output took too long")
                    time.sleep(0.05)
                process.wait(timeout=3)
                if process.returncode and not (self.stop.is_set() or self.interrupt.is_set() or not self.typed.empty()):
                    raise RuntimeError("Windows speech engine failed. Try the speech_worker.py test in TESTING.md")
            except Exception as e:  # noqa: BLE001
                self.speech_ok = False
                self.ui.log("system", f"Speech output unavailable: {safe_error(e)}. Replies remain visible; restart to retry.")
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait()
        self.ui.state("textonly" if self.text_mode else "listening")

    # ---- listening ----
    def _rms(self, data):
        return float(self.np.sqrt(self.np.mean(data ** 2)))

    def _calibrate(self):
        override = os.getenv("JARVIS_THRESHOLD", "").strip()
        if override:
            value = float(override)
            if not 0 < value <= 1:
                raise ValueError("JARVIS_THRESHOLD must be greater than 0 and at most 1")
            return value
        self.sd.check_input_settings(device=self.device, channels=1, samplerate=SAMPLE_RATE)
        chunks = []
        with self.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                 blocksize=1600, device=self.device) as stream:
            for _ in range(10):
                chunks.append(stream.read(1600)[0])
        return max(self._rms(self.np.concatenate(chunks)) * 3, 0.003)

    def _record(self, max_wait=None, max_len=30.0, end_silence=1.0):
        """Record one spoken phrase. Returns audio, or None if nobody spoke
        (or if we were muted, stopped, or the user typed something instead)."""
        np = self.np
        step = 0.1
        block = int(SAMPLE_RATE * step)
        preroll, chunks = [], []
        started, silent, waited = False, 0.0, 0.0
        with self.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                 blocksize=block, device=self.device) as stream:
            while True:
                if (self.stop.is_set() or self.muted.is_set() or self.capture_cancel.is_set()
                        or not self.typed.empty()):
                    return None
                data, _ = stream.read(block)
                data = data[:, 0]
                loud = self._rms(data) > self.threshold
                if not started:
                    if loud:
                        started = True
                        self.ui.state("hearing")
                        chunks = preroll + [data]
                    else:
                        preroll = (preroll + [data])[-3:]
                        waited += step
                        if max_wait and waited >= max_wait:
                            return None
                else:
                    chunks.append(data)
                    silent = 0.0 if loud else silent + step
                    if silent >= end_silence or len(chunks) * step >= max_len:
                        break
        return np.concatenate(chunks)

    def hear(self, max_wait=None):
        """Return what the user said or typed ('' if nothing useful).
        Sets self.last_typed so callers know if the wake word can be skipped."""
        self.last_typed = False
        self.check_audio()
        if self.text_mode and self.console:
            try:
                return input("You: ").strip()
            except EOFError:
                return "quit"
        if not self.typed.empty() or self.text_mode:
            try:
                text = self.typed.get(timeout=0.3 if self.text_mode else 0)
            except queue.Empty:
                return ""
            self.last_typed = True
            return text
        self.ui.state("listening")
        # Device drivers and transcription are native calls. Bound their wait so
        # a faulty device cannot also take away typing, mute, or shutdown.
        result = queue.Queue()
        self.capture_cancel.clear()
        def capture():
            try:
                result.put((True, self._listen_once(max_wait)))
            except Exception as error:
                result.put((False, safe_error(error)))
        thread = threading.Thread(target=capture, daemon=True, name="microphone")
        thread.start()
        deadline = time.monotonic() + (max_wait or 1) + 45
        cancelled_at = None
        while True:
            if self.stop.is_set() or self.muted.is_set() or not self.typed.empty():
                self.capture_cancel.set()
                if cancelled_at is None:
                    cancelled_at = time.monotonic()
            try:
                ok, value = result.get(timeout=0.05)
                break
            except queue.Empty:
                if time.monotonic() >= deadline or (cancelled_at is not None and time.monotonic() - cancelled_at > 1):
                    ok, value = False, "Microphone/transcription did not respond in time; restart to retry voice"
                    break
        if not ok:
            self.capture_cancel.set()
            self.text_mode = True
            self.audio_failed = True
            self.audio_ready = False
            self.ui.log("system", f"Voice unavailable: {value}. Typing still works.")
            self.ui.state("textonly")
            return ""
        if self.capture_cancel.is_set():
            return ""
        if value:
            self.ui.log("heard", value)
        self.ui.state("listening")
        return value

    def _listen_once(self, max_wait):
        audio = self._record(max_wait=max_wait or 1)
        if audio is None:
            return ""
        if len(audio) < SAMPLE_RATE * 0.4:
            return ""
        peak = float(self.np.max(self.np.abs(audio)))
        if peak > 0:  # boost quiet microphones so Whisper can hear them
            audio = audio / peak * 0.9
        segments, _ = self.stt.transcribe(
            audio, beam_size=3, vad_filter=False, condition_on_previous_text=False,
            initial_prompt=f"{WAKE_WORD.title()}, a voice assistant. {WAKE_WORD.title()}, what time is it?")
        text = " ".join(s.text for s in segments).strip()
        if not text:
            self.ui.log("note", "heard a sound but couldn't make out any words")
        return text

    def confirm(self, prompt):
        self.confirming = True
        try:
            return self._confirm(prompt)
        finally:
            self.confirming = False

    def _confirm(self, prompt):
        """Ask a yes/no question out loud. Anything unclear counts as 'no'."""
        if self.text_mode or self.muted.is_set() or not self.speech_ok:
            self.ui.log("system", "Email cancelled: a working, unmuted microphone and spoken read-back are required.")
            return False
        if self.stop.is_set():
            return False
        self.say(prompt)
        if not self.speech_ok or self.interrupt.is_set() or not self.typed.empty():
            return False
        # No prior transcript can authorize a send: hear() starts a fresh capture.
        self.ui.state("confirming")
        answer = self.hear(max_wait=10)
        if (self.last_typed or self.text_mode or self.muted.is_set()
                or self.stop.is_set() or self.interrupt.is_set()):
            return False
        words = set(re.findall(r"[a-z']+", answer.lower()))
        if words & NO_WORDS:
            return False
        return bool(words) and words <= YES_WORDS


# --------------------------------------------------------------------------
# Tools: what Jarvis can actually do
# --------------------------------------------------------------------------
def load_contacts():
    path = HERE / "contacts.json"
    if path.exists():
        return {k.lower(): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    return {}


def smtp_send(to, subject, body):
    user = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as server:
        server.login(user, password)
        server.send_message(msg)


def make_tools(client, voice):
    """Plain Python functions. Gemini reads their names, type hints and
    docstrings to learn what each tool does, and calls them automatically."""
    contacts = load_contacts()

    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email. The user is asked to confirm out loud before it is really sent.
        'to' can be a contact name (for example 'mom') or a full email address.

        Args:
            to: Contact name or email address.
            subject: Email subject line.
            body: Full plain-text email body.
        """
        try:
            address = to if "@" in to else contacts.get(to.lower().strip())
            if not address:
                return (f"No email address found for '{to}'. Ask the user for the address "
                        "(they can also add it to contacts.json).")
            if not os.getenv("EMAIL_ADDRESS") or not os.getenv("EMAIL_APP_PASSWORD"):
                return ("Email is not set up yet. Tell the user to fill in EMAIL_ADDRESS and "
                        "EMAIL_APP_PASSWORD in the .env file.")
            ok = voice.confirm(
                f"I'm about to email {to}, at {address}. The subject is: {subject}. "
                f"The message says: {body} Shall I send it?"
            )
            if not ok:
                return "The user did not confirm, so the email was NOT sent."
            if voice.stop.is_set() or voice.interrupt.is_set() or voice.muted.is_set():
                return "Email cancelled before sending."
            smtp_send(address, subject, body)
            return f"Email sent to {address}."
        except Exception as e:  # noqa: BLE001
            return f"Sending failed: {safe_error(e)}"

    def search_web(query: str) -> str:
        """Search the web with Google for current information: news, facts, weather,
        sports results, prices, anything that may have changed recently.

        Args:
            query: What to look up.
        """
        try:
            r = client.models.generate_content(
                model=MODEL,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            )
            return r.text or "No results found."
        except Exception as e:  # noqa: BLE001
            return f"Search failed: {safe_error(e)}"

    def get_current_datetime() -> str:
        """Get the current local date and time."""
        return datetime.now().strftime("%A, %d %B %Y, %H:%M")

    def open_website(url: str) -> str:
        """Open a website in the user's web browser.

        Args:
            url: The website address, for example youtube.com.
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened {url} in the browser."

    def set_reminder(minutes: float, message: str) -> str:
        """Remind the user after a number of minutes. Jarvis must remain running."""
        return voice.reminders.add(minutes, message)

    def list_reminders() -> str:
        """List pending reminders with local due dates."""
        return json.dumps(voice.reminders.items) if voice.reminders.items else "No pending reminders."

    def open_app(name: str) -> str:
        """Open an allowed Windows app by name: notepad, calculator, paint, explorer,
        or a name configured in apps.json. Never accepts shell commands."""
        apps = {"notepad": "notepad.exe", "calculator": "calc.exe",
                "paint": "mspaint.exe", "explorer": "explorer.exe"}
        custom_path = HERE / "apps.json"
        if custom_path.exists():
            custom = json.loads(custom_path.read_text(encoding="utf-8"))
            for label, path in custom.items():
                if isinstance(path, str) and Path(path).is_absolute() and Path(path).suffix.lower() == ".exe":
                    apps[label.lower()] = path
        target = apps.get(name.lower().strip())
        if target is None:
            return "App not configured. Available names: " + ", ".join(sorted(apps))
        try:
            subprocess.Popen([target], shell=False)
            return f"Opened {name}."
        except OSError as error:
            return f"Could not open app: {safe_error(error)}"

    return [send_email, search_web, get_current_datetime, open_website,
            set_reminder, list_reminders, open_app]


# --------------------------------------------------------------------------
# Brain: Gemini decides what to do
# --------------------------------------------------------------------------
class Assistant:
    def __init__(self, voice):
        self.voice = voice
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                                   http_options=types.HttpOptions(timeout=30000))
        who = f" The user's name is {USER_NAME}; sign emails with it." if USER_NAME else ""
        system = (
            "You are Jarvis, a helpful voice assistant running on the user's laptop. "
            "Your replies are read aloud, so keep them short and natural: one to three "
            "sentences, no markdown, no bullet points, no asterisks, no emoji, no URLs read out. "
            "Speech recognition can make mistakes, so if a request is unclear, ask a short "
            "clarifying question. Use your tools to act, and only say something was done "
            "if the tool result confirms it. For emails, write a polite, clear message. "
            "If asked for the date or time, use your tool rather than guessing. "
            f"Today is {datetime.now().strftime('%A, %d %B %Y')}.{who}"
        )
        # A chat object remembers the conversation and runs tool calls automatically.
        self.chat = self.client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=make_tools(self.client, voice),
            ),
        )

    def ask(self, text):
        try:
            reply = (self.chat.send_message(text).text or "").strip()
        except Exception as e:  # noqa: BLE001
            self.voice.ui.log("system", f"API error: {safe_error(e)}")
            return "Sorry, I couldn't reach my brain just now. Please try again."
        return reply or "Done."


# --------------------------------------------------------------------------
# Main loop (shared by the terminal version and the desktop app)
# --------------------------------------------------------------------------
def run_loop(voice, assistant, ui, stop, allow_quit=True):
    while not stop.is_set():
        voice.check_audio()
        for reminder in voice.reminders.take_due():
            ui.log("notification", "Reminder: " + reminder["text"])
            voice.say("Reminder: " + reminder["text"])
        if voice.muted.is_set() and voice.typed.empty():
            ui.state("muted")
            time.sleep(0.2)
            continue

        heard = voice.hear()
        if not heard:
            continue

        if voice.text_mode or voice.last_typed:
            command = heard                      # typed: no wake word needed
        else:
            command = wake_command(heard)
            if command is None:
                continue                         # not for me
            if not command:
                voice.say("Yes?")
                command = voice.hear(max_wait=8)
                if not command:
                    continue

        ui.log("user", command)
        if allow_quit and command.lower().strip(" .!?") in QUIT_PHRASES:
            voice.say("Goodbye.")
            break

        ui.state("thinking")
        voice.say(assistant.ask(command))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="type instead of using the microphone")
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is missing. Copy .env.example to .env and fill it in.")

    ui = ConsoleUI()
    voice = Voice(text_mode=args.text, ui=ui, console=args.text)
    assistant = Assistant(voice)

    if args.text:
        voice.say("Text mode. Type a request, or 'quit' to leave.")
    else:
        voice.say(f"Jarvis online. Say {WAKE_WORD} and then your request.")

    try:
        run_loop(voice, assistant, ui, voice.stop, allow_quit=True)
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
