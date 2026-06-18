from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
import sounddevice as sd

from config import audio_config
from decoder import decode_packets_from_audio, reconstruct_and_decrypt
from logging_utils import get_logger


logger = get_logger(__name__)


def record_audio(duration_s: float) -> np.ndarray:
    """
    Record mono audio from default input device.
    """
    logger.info("Recording audio for %.2fs", duration_s)
    sr = audio_config.sample_rate
    data = sd.rec(int(duration_s * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    mono = data[:, 0]
    return mono


def receive_and_decode(
    duration_s: float,
    password: str,
) -> Tuple[bytes | None, dict | None, List[Tuple[float, float]]]:
    """
    Capture audio for a fixed duration, decode packets, and decrypt payload.

    Returns: (plaintext_bytes, header, peak_log)
    """
    samples = record_audio(duration_s)
    packets, peak_log = decode_packets_from_audio(samples, audio_config.sample_rate)
    plaintext, header = reconstruct_and_decrypt(packets, password=password)
    return plaintext, header, peak_log


def save_received_file(
    plaintext: bytes,
    header: dict,
    output_dir: Path,
) -> Path:
    """
    Save reconstructed file according to header metadata.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    file_name = header.get("file_name") or "received.bin"
    target = output_dir / file_name
    with target.open("wb") as f:
        f.write(plaintext)
    logger.info("Saved received file to %s", target)
    return target

