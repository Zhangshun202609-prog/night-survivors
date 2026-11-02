"""Makes the short sound files in sounds/ from the recipes in data/game.json.

Standard library only, so this runs anywhere. main.py never imports this file -
it only loads the .wav files this script writes.
Run it with:  python make_sounds.py
"""

import json
import math
import os
import struct
import wave

from rules import load_data

# A tiny random number generator of our own, so the noise is the same every run.
class Noise:
    def __init__(self):
        self.state = 12345

    def next(self):
        self.state = (self.state * 1103515245 + 12345) % (2 ** 31)
        return self.state / (2 ** 31) * 2.0 - 1.0


def wave_value(kind, phase, noise):
    """One sample of a plain wave. phase is 0..1 for a full cycle."""
    if kind == "sine":
        return math.sin(math.tau * phase)
    if kind == "square":
        return 1.0 if phase < 0.5 else -1.0
    if kind == "triangle":
        return 4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase
    if kind == "noise":
        return noise.next()
    raise ValueError(f"unknown wave kind: {kind}")


def render_part(part, rate, noise):
    """Turn one recipe into a list of samples between -1 and 1."""
    length = part["length"]
    count = int(round(length * rate))
    start = part["from"]
    end = part["to"]
    samples = []
    phase = 0.0
    for i in range(count):
        t = i / rate
        freq = start + (end - start) * (t / length if length else 0.0)
        phase = (phase + freq / rate) % 1.0
        fade = math.exp(-part["decay"] * t)
        samples.append(wave_value(part["wave"], phase, noise) * fade * part["volume"])
    return samples


def write_wav(path, samples, rate):
    """Mono, 16-bit, no compression - the format pygame reads without extra libraries."""
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        clipped = [max(-1.0, min(1.0, s)) for s in samples]
        f.writeframes(struct.pack("<%dh" % len(clipped), *[int(s * 32767) for s in clipped]))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data = load_data(os.path.join(here, "data", "game.json"))
    maker = data["sound_maker"]
    rate = maker["sample_rate"]
    out_dir = os.path.join(here, maker["dir"])
    os.makedirs(out_dir, exist_ok=True)
    for name, recipe in maker["sounds"].items():
        noise = Noise()
        samples = []
        for part in recipe["parts"]:
            samples.extend(render_part(part, rate, noise))
        path = os.path.join(out_dir, f"{name}.wav")
        write_wav(path, samples, rate)
        size = os.path.getsize(path)
        print(f"{name}.wav  {len(samples) / rate:.2f} s  {size} bytes")
    print(f"\nDone. Files are in {maker['dir']}/")


if __name__ == "__main__":
    main()
