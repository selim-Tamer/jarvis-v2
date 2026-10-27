"""Windows tray and an owned Edge app window; no browser speech APIs."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import webbrowser

import jarvis


class Desktop:
    def __init__(self, runtime, url):
        self.runtime = runtime
        self.url = url
        self.tray = None
        self.tray_ready = False
        self.browser = None
        self.lock = threading.Lock()
        self.hidden = False
        self.last_launch = 0

    def _windows(self):
        if os.name != "nt" or self.browser is None:
            return []
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        result = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, data):
            process = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
            if process.value == self.browser.pid:
                title = ctypes.create_unicode_buffer(1024)
                user32.GetWindowTextW(hwnd, title, len(title))
                if title.value.startswith("Jarvis v2.0"):
                    result.append(hwnd)
            return True
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows(callback_type(visit), 0)
        return result

    def show(self):
        with self.lock:
            self.hidden = False
            windows = self._windows()
            if windows:
                for hwnd in windows:
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 9)
                    ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))
                return
            if self.browser is not None and time.monotonic() - self.last_launch < 3:
                return
            candidates = [Path(os.getenv(root, "")) / "Microsoft/Edge/Application/msedge.exe"
                          for root in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
            edge = next((path for path in candidates if path.is_file()), None)
            if edge:
                profile = Path(__file__).resolve().parent / ".edge-profile"
                self.browser = subprocess.Popen([
                    str(edge), "--app=" + self.url, "--user-data-dir=" + str(profile),
                    "--no-first-run", "--no-default-browser-check", "--disable-background-mode"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.last_launch = time.monotonic()
            else:
                webbrowser.open(self.url)
                self.runtime.ui.log("system", "Opened the default browser. Hide to tray requires the dedicated Edge window; minimise this browser manually.")

    def hide(self):
        from fastapi import HTTPException
        if not self.tray_ready:
            raise HTTPException(409, "The tray icon is not ready. Keep the window open or minimise it.")
        windows = self._windows()
        if not windows:
            raise HTTPException(409, "Cannot find the owned Edge window. Minimise the browser manually; Jarvis stays running.")
        for hwnd in windows:
            ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 0)
        self.hidden = True
        self.notify("Jarvis is still running. Use the tray icon to reopen it.")

    def notify(self, text):
        if self.tray_ready:
            try:
                self.tray.notify(jarvis.safe_error(text), "Jarvis v2.0")
            except Exception as error:
                self.runtime.ui.log("system", "Notification unavailable: " + jarvis.safe_error(error))

    def start_tray(self):
        def run():
            try:
                import pystray
                from PIL import Image, ImageDraw
                image = Image.new("RGBA", (64,64))
                draw = ImageDraw.Draw(image)
                draw.ellipse((4,4,60,60), fill="#38bdf8")
                draw.ellipse((20,20,44,44), fill="#060a14")
                def invoke(action):
                    try:
                        if action == "toggle":
                            action = "unmute" if self.runtime.muted.is_set() else "mute"
                        self.runtime.control(action)
                    except Exception as error:
                        self.runtime.ui.log("system", jarvis.safe_error(error))
                self.tray = pystray.Icon("Jarvis v2.0", image, "Jarvis v2.0", pystray.Menu(
                    pystray.MenuItem("Open Jarvis", lambda: invoke("show"), default=True),
                    pystray.MenuItem("Mute microphone", lambda: invoke("toggle"), checked=lambda item:self.runtime.muted.is_set()),
                    pystray.MenuItem("Stop speaking", lambda: invoke("interrupt")),
                    pystray.MenuItem("Quit", lambda: invoke("quit"))))
                def ready(icon):
                    if self.runtime.stop.is_set():
                        icon.stop()
                        return
                    icon.visible = True
                    self.tray_ready = True
                    self.runtime.emit("status")
                self.tray.run(setup=ready)
            except Exception as error:
                self.runtime.ui.log("system", "Tray unavailable: " + jarvis.safe_error(error))
            finally:
                self.tray_ready = False
        threading.Thread(target=run, daemon=True, name="tray").start()

    def open_when_ready(self, hidden=False):
        self.hidden = hidden
        def wait():
            for _ in range(100):
                if self.runtime.stop.is_set():
                    return
                try:
                    with socket.create_connection(("127.0.0.1",8000), timeout=.2):
                        pass
                    # Hidden startup is only safe when the tray is usable.
                    if hidden and not self.tray_ready:
                        time.sleep(.1)
                        continue
                    if not hidden or self.runtime.state == "error" or (self.runtime.voice and self.runtime.voice.audio_failed):
                        self.show()
                    return
                except OSError:
                    time.sleep(.1)
            self.runtime.ui.log("system", "Desktop startup took too long. Open http://127.0.0.1:8000 or check the console.")
            if hidden:
                self.show()
        threading.Thread(target=wait, daemon=True, name="desktop-startup").start()

    def close(self):
        for hwnd in self._windows():
            ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
        if self.tray is not None:
            self.tray.stop()
