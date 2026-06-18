from __future__ import annotations

from typing import List

import numpy as np
import sounddevice as sd

from ai_engine import analyze_ambient_noise, choose_base_frequency
from config import audio_config, packet_config
from crypto import EncryptedPayload, encrypt_payload
from encoder import Packet, build_packets, packet_to_waveform, get_alphabet
from logging_utils import get_logger


logger = get_logger(__name__)


def prepare_encrypted_packets(
    message_type: str,
    plaintext_payload: bytes,
    password: str,
    file_name: str | None = None,
) -> List[Packet]:
    """
    High-level helper: analyze noise, encrypt payload, and build packets.
    """
    noise_profile = analyze_ambient_noise()
    base_freq = choose_base_frequency(noise_profile, num_symbols=len(get_alphabet()))

    encrypted: EncryptedPayload = encrypt_payload(password, plaintext_payload)

    packets = build_packets(
        message_type=message_type,
        plaintext_payload=plaintext_payload,
        file_name=file_name,
        password=password,
        encrypted=encrypted,
        base_frequency_hz=base_freq,
    )
    return packets


def transmit_packets(packets: List[Packet]) -> None:
    """
    Play packet waveforms over the default output device.
    """
    if not packets:
        logger.warning("No packets to transmit")
        return

    waveforms: List[np.ndarray] = []
    for pkt in packets:
        for _ in range(packet_config.redundancy_copies):
            wf = packet_to_waveform(pkt)
            waveforms.append(wf)

    stream = np.concatenate(waveforms) if waveforms else np.zeros(1, dtype=np.float32)
    logger.info(
        "Transmitting waveform with %d samples (%.2fs)",
        len(stream),
        len(stream) / audio_config.sample_rate,
    )
    sd.play(stream, samplerate=audio_config.sample_rate, blocking=True)
    sd.wait()
    logger.info("Transmission complete")

