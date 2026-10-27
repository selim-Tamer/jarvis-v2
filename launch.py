"""Start the Python assistant, local web UI, and Windows tray together."""
import argparse
from pathlib import Path
import socket
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="No microphone or speaker; spoken email confirmation unavailable")
    parser.add_argument("--hidden", action="store_true", help="Start in tray")
    parser.add_argument("--no-browser", action="store_true", help="Start server without opening a window")
    parser.add_argument("--no-tray", action="store_true", help="Disable the tray icon")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    if sys.stdout is None or sys.stderr is None:
        log = open(here / "jarvis.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1",47654))
    except OSError:
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")
        print("Jarvis v2 is already running. Use its tray icon to open or quit it.")
        return
    if not (here / "dist/index.html").exists():
        raise SystemExit("Frontend missing. Run npm.cmd ci, then npm.cmd run build in this folder.")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1",8000))
        except OSError:
            raise SystemExit("Port 8000 is in use. Stop the other server, then run launch.py again.") from None
    import uvicorn
    from desktop import Desktop
    from server import Runtime, create_app
    runtime = Runtime(text_only=args.text)
    desktop = Desktop(runtime, "http://127.0.0.1:8000")
    runtime.desktop = desktop
    server = uvicorn.Server(uvicorn.Config(create_app(runtime), host="127.0.0.1", port=8000,
                                           access_log=False, timeout_graceful_shutdown=3))
    runtime.shutdown_callback = lambda: setattr(server, "should_exit", True)
    if not args.no_tray:
        desktop.start_tray()
    if not args.no_browser:
        desktop.open_when_ready(hidden=args.hidden and not args.no_tray)
    print("Jarvis v2: http://127.0.0.1:8000 (Ctrl+C or Quit to stop)")
    try:
        server.run()
    finally:
        runtime.close()
        desktop.close()
        lock.close()


if __name__ == "__main__":
    main()
