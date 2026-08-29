# Assets

- **`activation_chime.wav`** — played the instant the wake word is detected
  (`heypeer/wakeword/listener.py`'s `play_activation_chime`). Mono, 16 kHz,
  int16, trimmed to ~0.66s, normalized with headroom.

  Generated from `freesound_community-beep-6-96243.mp3` (kept here for
  provenance — sourced from the Freesound community). It ships pre-decoded
  as WAV rather than being decoded at runtime because mp3 support in
  libsndfile only exists from 1.1 onward and isn't guaranteed on every
  install, and because WAV keeps playback on the same int16/pyaudio path the
  rest of the audio pipeline already uses.

  To regenerate after replacing the source file:

  ```python
  import numpy as np, soundfile as sf
  data, sr = sf.read("heypeer/assets/<source>.mp3")
  mono = data.mean(axis=1) if data.ndim > 1 else data
  target = 16000
  n = int(len(mono) * target / sr)
  res = np.interp(np.linspace(0, len(mono), n, endpoint=False), np.arange(len(mono)), mono)
  amp = np.abs(res); idx = np.nonzero(amp > amp.max() * 0.02)[0]
  res = res[idx[0]:idx[-1] + 1]
  res = res / np.abs(res).max() * 0.55
  sf.write("heypeer/assets/activation_chime.wav", (res * 32767).astype("int16"), target,
           subtype="PCM_16")
  ```
