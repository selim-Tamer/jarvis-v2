"""Microphone check. Run it with the venv python, optionally followed by a device number."""
import sys
import numpy as np
import sounddevice as sd

print("Input devices (number: name):")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        mark = "  <-- default" if i == sd.default.device[0] else ""
        print(f"  {i}: {d['name']}{mark}")

device = int(sys.argv[1]) if len(sys.argv) > 1 else None
print(f"\nUsing device: {device if device is not None else 'default'}")
print("Speak normally for 6 seconds. The bar should jump when you talk.\n")
try:
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                        blocksize=1600, device=device) as stream:
        for _ in range(60):
            data, _ = stream.read(1600)
            rms = float(np.sqrt(np.mean(data ** 2)))
            print(f"{rms:.4f} " + "#" * min(int(rms * 400), 60))
except Exception as e:
    print("ERROR opening microphone:", e)
