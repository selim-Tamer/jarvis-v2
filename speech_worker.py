"""One utterance per process: keeps Windows COM and message pumping together."""
import json
import sys


def main():
    try:
        import pyttsx3
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.say(payload["text"])
        engine.runAndWait()
        engine.stop()
    except Exception:
        # Do not dump library exceptions or environment variables to pythonw logs.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
