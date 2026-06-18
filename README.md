Sonar-Share: AI-Driven Air-Gapped Acoustic Communication System
===============================================================

Overview
--------

Sonar-Share is a modular, production-grade prototype for securely transmitting
encrypted data over an **acoustic-only** channel (speaker → air → microphone)
without any use of WiFi, Bluetooth, NFC, or RF communication.

Core capabilities:
- Encrypted FSK-based data transmission around 9 kHz
- Text, coordinates, and small file (\<10 KB) transfer
- Adaptive AI-like engine for noise-aware transmission
- Basic forward error detection and packet integrity checks
- Clean, extensible Python 3.11+ architecture

Project Structure
-----------------

- `main.py` — CLI entrypoint for transmitter/receiver modes.
- `encoder.py` — Symbol mapping, packetization, FSK tone sequence generation.
- `decoder.py` — Audio FFT analysis, symbol detection, packet reconstruction.
- `crypto.py` — AES-256-CBC encryption/decryption utilities and key handling.
- `ai_engine.py` — Adaptive logic (noise analysis, frequency/threshold tuning).
- `transmitter.py` — High-level transmit pipeline using sounddevice.
- `receiver.py` — High-level receive pipeline using sounddevice.
- `config.py` — Shared configuration (sample rates, symbol durations, etc.).
- `logging_utils.py` — Central logging and debug-mode helpers.
- `gui.py` — Professional PyQt6 desktop GUI application.

Getting Started
---------------

### Option 1: GUI Application (Recommended)

Launch the graphical interface:

```bash
python gui.py
```

The GUI provides:
- **Send Mode**: Enter text, coordinates, or select files (<10 KB)
- **Receive Mode**: Start listening and view decrypted output
- **Real-time Status**: AI engine metrics, encryption status, signal confidence
- **Logs Panel**: Detailed transmission/reception logs

**Usage:**
1. Enter encryption password in the password field
2. For sending: Enter text/coordinates or select a file, then click the appropriate send button
3. For receiving: Set listen duration and click "Start Listening"
4. View decrypted output, confidence scores, and detected frequencies in real-time

### Option 2: Command-Line Interface

1. **Install dependencies** (Python 3.11+ recommended):

   ```bash
   pip install -r requirements.txt
   ```

2. **Run transmitter** (example text message):

   ```bash
   python main.py transmit --mode text --message "HELLO SONAR" --password "strong-pass"
   ```

3. **Run receiver** (on another machine or the same one with mic input):

   ```bash
   python main.py receive --mode text --password "strong-pass"
   ```

4. **File transfer \<10 KB**:

   ```bash
   python main.py transmit --mode file --file-path small.bin --password "strong-pass"
   python main.py receive --mode file --password "strong-pass" --output-dir received_files
   ```

Security Notes
--------------

- All payloads (text, coordinates, files) are encrypted using AES-256 in CBC mode.
- The IV is freshly generated per message and sent in the encrypted header.
- No networking or socket APIs are used; the only channel is sound.

Limitations & Tuning
--------------------

- This is a **production-grade prototype**, not a turnkey product. You may need
  to tune symbol duration, gain, and thresholds depending on your hardware.
- Real-world performance depends on room acoustics, background noise, and
  microphone/speaker quality.

License
-------

This project is provided as-is for research, experimentation, and educational
purposes. Review and adapt the code before using it in production environments.

