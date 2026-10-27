"""Developer smoke fixture. Fake Gemini and text mode; never sends email."""
import os
import sys
from unittest.mock import patch

if __name__ == "__main__":
    os.environ["GEMINI_API_KEY"] = "offline-fake-key"
    os.environ["EMAIL_ADDRESS"] = "offline@example.com"
    os.environ["EMAIL_APP_PASSWORD"] = "offline-fake-password"
    import jarvis
    import launch

    class OfflineAssistant:
        def __init__(self, voice):
            self.voice = voice

        def ask(self, text):
            if text.lower() == "test email cancellation":
                tool = jarvis.make_tools(None, self.voice)[0]
                return tool("offline@example.com", "Offline test", "This must not send")
            return "Offline connection test passed. Python received: " + text

    sys.argv = ["launch.py", "--text"]
    with patch.object(jarvis, "Assistant", OfflineAssistant), patch.object(jarvis, "smtp_send", side_effect=AssertionError("SMTP must never be reached")):
        launch.main()
