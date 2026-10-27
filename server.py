"""Local React bridge. All assistant work stays in one Python worker thread."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import jarvis

HERE = Path(__file__).resolve().parent


class BridgeUI:
    def __init__(self, runtime):
        self.runtime = runtime

    def state(self, name):
        rt = self.runtime
        if rt.voice is not None and rt.voice.confirming and name in {"listening", "hearing"}:
            name = "confirming"
        if name == "listening" and rt.muted.is_set():
            name = "muted"
        with rt.lock:
            rt.state = name
            if name == "thinking":
                rt.busy = True
            rt.emit("status")

    def log(self, who, text):
        rt = self.runtime
        text = jarvis.safe_error(text)
        with rt.lock:
            if who in {"heard", "note"}:
                rt.heard = text
                rt.emit("status")
                return
            if who == "system":
                rt.detail = text
            if who == "user":
                rt.busy = True
                rt.detail = "Processing your request..."
            if who == "jarvis" and not (rt.voice and rt.voice.confirming):
                rt.busy = False
                rt.detail = "Reply ready. Type below or use your wake word."
            message = {"id": rt.next_message, "role": who, "text": text}
            rt.next_message += 1
            rt.messages.append(message)
            rt.emit("message", message=message)
        if who == "notification" and rt.desktop is not None:
            rt.desktop.notify(text)
        if (who == "system" and rt.desktop is not None and rt.desktop.hidden
                and any(word in text.lower() for word in ("stopped", "unavailable", "timed out", "failed"))):
            rt.desktop.show()


class Runtime:
    def __init__(self, text_only=False, assistant_factory=None):
        self.text_only = text_only
        self.assistant_factory = assistant_factory or jarvis.Assistant
        self.lock = threading.RLock()
        self.events = deque(maxlen=600)
        self.messages = deque(maxlen=200)
        self.next_message = 1
        self.sequence = 0
        self.stop = threading.Event()
        self.muted = threading.Event()
        self.interrupt = threading.Event()
        self.typed = queue.Queue()
        self.voice = None
        self.ready = False
        self.busy = False
        self.state = "loading"
        self.detail = "Starting Python assistant..."
        self.heard = ""
        self.reset_requested = threading.Event()
        self.thread = None
        self.desktop = None
        self.shutdown_callback = None
        self.ui = BridgeUI(self)
        self.started_at = time.monotonic()

    def status(self):
        with self.lock:
            return {"state": self.state, "detail": self.detail, "ready": self.ready,
                    "busy": self.busy, "muted": self.muted.is_set(),
                    "confirming": bool(self.voice and self.voice.confirming),
                    "voice_ready": bool(self.voice and not self.voice.text_mode),
                    "wake_word": jarvis.WAKE_WORD, "model": jarvis.MODEL,
                    "desktop": bool(self.desktop),
                    "tray_ready": bool(self.desktop and self.desktop.tray_ready)}

    def snapshot(self):
        with self.lock:
            return {"type": "snapshot", "status": self.status(),
                    "messages": list(self.messages), "heard": self.heard,
                    "cursor": self.sequence}

    def emit(self, kind, **data):
        with self.lock:
            self.sequence += 1
            self.events.append((self.sequence, {"type": kind, "status": self.status(),
                                               "heard": self.heard, **data}))

    def start(self):
        self.started_at = time.monotonic()
        self.thread = threading.Thread(target=self.worker, daemon=True, name="assistant")
        self.thread.start()

    def worker(self):
        try:
            self.ui.log("system", "Step 1/3: checking local configuration...")
            if not os.getenv("GEMINI_API_KEY"):
                raise ValueError("GEMINI_API_KEY is missing. Put your settings in this folder's .env file and restart.")
            self.ui.log("system", "Step 2/3: preparing Python voice bridge...")
            self.voice = jarvis.Voice(text_mode=True, ui=self.ui, typed=self.typed,
                                      stop=self.stop, muted=self.muted, interrupt=self.interrupt)
            self.ui.log("system", "Step 3/3: preparing Gemini chat...")
            assistant = self.assistant_factory(self.voice)
            rt = self

            class SerializedAssistant:
                def ask(self, text):
                    nonlocal assistant
                    if rt.reset_requested.is_set():
                        assistant = rt.assistant_factory(rt.voice)
                        rt.reset_requested.clear()
                    return assistant.ask(text)

            self.ready = True
            self.ui.log("system", "Typing ready. Voice loads separately." if not self.text_only else "Text-only mode ready. Email requires spoken confirmation and is disabled in this mode.")
            self.ui.state("textonly")
            if not self.text_only:
                self.voice.start_audio()
            jarvis.run_loop(self.voice, SerializedAssistant(), self.ui, self.stop, allow_quit=False)
        except Exception as error:
            self.ready = False
            self.busy = False
            self.ui.log("system", "Assistant stopped: " + jarvis.safe_error(error))
            self.ui.state("error")

    def submit(self, text):
        with self.lock:
            if self.stop.is_set() or not self.ready:
                raise HTTPException(503, self.detail)
            if self.busy or (self.voice and self.voice.confirming):
                raise HTTPException(409, "Finish the current request first. Email confirmation must be spoken; use Stop speaking to cancel it.")
            self.busy = True
            self.interrupt.set()
            self.typed.put(text)
            self.emit("status")

    def clear(self):
        with self.lock:
            if self.busy:
                raise HTTPException(409, "Wait for the current request before clearing the conversation.")
            self.reset_requested.set()
            self.messages.clear()
            self.heard = ""
            self.detail = "Conversation cleared. Type below or use your wake word."
            self.emit("clear")

    def control(self, action):
        if action in {"mute", "unmute"}:
            if action == "mute":
                self.muted.set()
            else:
                self.muted.clear()
            if self.voice and self.voice.confirming:
                self.interrupt.set()
                self.voice.capture_cancel.set()
            if not self.busy and self.state != "speaking":
                self.ui.state("muted" if self.muted.is_set() else "listening" if self.voice and not self.voice.text_mode else "textonly")
            else:
                self.emit("status")
        elif action == "interrupt":
            self.interrupt.set()
            if self.voice and self.voice.confirming:
                self.voice.capture_cancel.set()
            self.emit("status")
        elif action == "quit":
            self.close()
            if self.shutdown_callback:
                threading.Timer(0.2, self.shutdown_callback).start()
        elif action in {"hide", "show"}:
            if self.desktop is None:
                raise HTTPException(409, "Start with launch.py for desktop/tray controls.")
            getattr(self.desktop, action)()

    def close(self):
        self.ready = False
        self.stop.set()
        self.interrupt.set()
        if self.voice:
            self.voice.capture_cancel.set()
        self.state = "stopped"
        self.detail = "Jarvis has stopped. Close this window."
        self.emit("status")

    async def stream(self, request):
        snapshot = self.snapshot()
        cursor = snapshot["cursor"]
        yield "data: " + json.dumps(snapshot) + "\n\n"
        heartbeat = time.monotonic()
        while not self.stop.is_set():
            if await request.is_disconnected():
                return
            with self.lock:
                events = [(seq, event) for seq, event in self.events if seq > cursor]
                fell_behind = bool(self.events and cursor < self.events[0][0] - 1)
            if fell_behind:
                snapshot = self.snapshot()
                cursor = snapshot["cursor"]
                yield "data: " + json.dumps(snapshot) + "\n\n"
            else:
                for seq, event in events:
                    cursor = seq
                    yield f"id: {seq}\ndata: {json.dumps(event)}\n\n"
            if not self.ready and self.state == "loading" and time.monotonic() - self.started_at > 20:
                self.ui.log("system", "Startup is taking over 20 seconds. Restart and check the last startup step.")
                self.ui.state("error")
            if time.monotonic() - heartbeat > 10:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.1)
        yield "data: " + json.dumps({"type": "status", "status": self.status()}) + "\n\n"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class ControlRequest(BaseModel):
    action: Literal["mute", "unmute", "interrupt", "hide", "show", "quit"]


def create_app(runtime=None, start_worker=True):
    rt = runtime or Runtime()
    session = secrets.token_urlsafe(32)
    origins = {"http://127.0.0.1:8000", "http://localhost:8000",
               "http://127.0.0.1:5173", "http://localhost:5173"}

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            rt.start()
        yield
        rt.close()
        if rt.thread:
            await asyncio.to_thread(rt.thread.join, 1.5)

    application = FastAPI(lifespan=lifespan)
    application.state.runtime = rt
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    application.add_middleware(CORSMiddleware, allow_origins=sorted(origins),
                               allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                               allow_credentials=True)

    @application.middleware("http")
    async def local_session(request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in origins:
                return JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)
            if request.url.path != "/api/health" and not secrets.compare_digest(request.cookies.get("jarvis_session", ""), session):
                return JSONResponse({"detail": "Reconnect to Jarvis first"}, status_code=403)
        return await call_next(request)

    @application.get("/api/health")
    async def health():
        response = JSONResponse({"ok": True, "app": "jarvis-v2", **rt.status()})
        response.set_cookie("jarvis_session", session, httponly=True, samesite="strict")
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/api/events")
    async def events(request: Request):
        return StreamingResponse(rt.stream(request), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @application.post("/api/chat", status_code=202)
    async def chat(body: ChatRequest):
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "Type a message first")
        rt.submit(text)
        return {"accepted": True}

    @application.post("/api/control")
    async def control(body: ControlRequest):
        rt.control(body.action)
        return {"ok": True}

    @application.post("/api/clear")
    async def clear():
        rt.clear()
        return {"ok": True}

    if (HERE / "dist").exists():
        application.mount("/", StaticFiles(directory=str(HERE / "dist"), html=True), name="frontend")
    return application


app = create_app()
