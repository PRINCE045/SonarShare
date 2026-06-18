from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import get_window

from config import audio_config
from crypto import EncryptedPayload, decode_base64_from_sonar, decrypt_payload
from encoder import get_alphabet, symbols_to_text
from ai_engine import ThresholdState, create_threshold_state
from logging_utils import get_logger


logger = get_logger(__name__)


SONAR_ALPHABET = get_alphabet()
_char_to_symbol: Dict[str, int] = {ch: i for i, ch in enumerate(SONAR_ALPHABET)}


@dataclass
class DecodedPacket:
    header: dict
    payload_fragment_sonar_b64: str


def _frequency_to_symbol(
    freq_hz: float, base_frequency_hz: float
) -> Optional[int]:
    step = audio_config.frequency_step_hz
    rel = freq_hz - base_frequency_hz
    sym = int(round(rel / step))
    expected_freq = base_frequency_hz + sym * step
    if (
        abs(expected_freq - freq_hz) > audio_config.detection_tolerance_hz
        or sym < 0
        or sym >= len(SONAR_ALPHABET)
    ):
        return None
    return sym


def _detect_symbol_for_frame(
    frame: np.ndarray, sr: int, state: ThresholdState
) -> Tuple[Optional[int], float, float]:
    """
    Run FFT on a single frame and return detected symbol (if any),
    its peak frequency, and confidence.
    """
    if frame.size == 0:
        return None, 0.0, 0.0

    window = get_window(audio_config.fft_window, frame.size)
    windowed = frame * window
    spectrum = np.fft.rfft(windowed)
    freqs = np.fft.rfftfreq(frame.size, d=1.0 / sr)
    mags = np.abs(spectrum)

    band_mask = (freqs >= audio_config.expected_band_low_hz) & (
        freqs <= audio_config.expected_band_high_hz
    )
    freqs_band = freqs[band_mask]
    mags_band = mags[band_mask]

    if freqs_band.size == 0:
        return None, 0.0, 0.0

    peak_idx = int(np.argmax(mags_band))
    peak_freq = float(freqs_band[peak_idx])
    peak_mag = float(mags_band[peak_idx])

    _, confidence, accepted = state.update(peak_mag, mags_band)
    if not accepted:
        return None, peak_freq, confidence

    # base_frequency_hz for mapping is recovered from header later; here we only
    # store the peak frequencies symbol by symbol per packet.
    return None, peak_freq, confidence


def _segment_into_frames(samples: np.ndarray, sr: int) -> List[np.ndarray]:
    symbol_len = int(audio_config.symbol_duration_s * sr)
    frame_count = len(samples) // symbol_len
    frames = [
        samples[i * symbol_len : (i + 1) * symbol_len] for i in range(frame_count)
    ]
    return frames


def decode_packets_from_audio(
    samples: np.ndarray, sr: int
) -> Tuple[List[DecodedPacket], List[Tuple[float, float]]]:
    """
    High-level decoding: split samples into frames, run spectral peak detection,
    and reconstruct packets from symbol stream.
    """
    frames = _segment_into_frames(samples, sr)
    state = create_threshold_state()
    # We store only peak frequencies and confidences; symbol mapping needs base
    # frequency from the packet header, which is embedded in JSON.
    peak_log: List[Tuple[float, float]] = []

    # First pass: detect peaks and build approximate text assuming the default base.
    # We use configured base for rough symbol mapping just to recover JSON, then
    # refine using per-packet base_frequency_hz.
    rough_base = audio_config.base_frequency_hz
    rough_symbols: List[int] = []

    for frame in frames:
        window = get_window(audio_config.fft_window, frame.size)
        windowed = frame * window
        spectrum = np.fft.rfft(windowed)
        freqs = np.fft.rfftfreq(frame.size, d=1.0 / sr)
        mags = np.abs(spectrum)

        band_mask = (freqs >= audio_config.expected_band_low_hz) & (
            freqs <= audio_config.expected_band_high_hz
        )
        freqs_band = freqs[band_mask]
        mags_band = mags[band_mask]
        if freqs_band.size == 0:
            continue

        peak_idx = int(np.argmax(mags_band))
        peak_freq = float(freqs_band[peak_idx])
        peak_mag = float(mags_band[peak_idx])

        _, confidence, accepted = state.update(peak_mag, mags_band)
        peak_log.append((peak_freq, confidence))
        if not accepted:
            continue

        sym = _frequency_to_symbol(peak_freq, rough_base)
        if sym is not None:
            rough_symbols.append(sym)

    if not rough_symbols:
        logger.warning("No symbols detected from audio")
        return [], peak_log

    rough_text = symbols_to_text(rough_symbols)

    # Split rough stream into framed packets using "::" markers.
    packets: List[DecodedPacket] = []
    marker = "::"
    while True:
        start = rough_text.find(marker)
        if start == -1:
            break
        end = rough_text.find(marker, start + len(marker))
        if end == -1:
            break
        payload_text = rough_text[start + len(marker) : end]
        rough_text = rough_text[end + len(marker) :]

        try:
            obj = json.loads(payload_text)
            header = obj.get("h", {})
            payload_fragment = obj.get("p", "")
            packets.append(
                DecodedPacket(
                    header=header,
                    payload_fragment_sonar_b64=payload_fragment,
                )
            )
        except json.JSONDecodeError:
            logger.debug("Discarding malformed packet candidate")
            continue

    logger.info("Decoded %d packets from audio", len(packets))
    return packets, peak_log


def reconstruct_and_decrypt(
    packets: List[DecodedPacket],
    password: str,
) -> Tuple[Optional[bytes], Optional[dict]]:
    """
    Reassemble encrypted blob from packets, verify CRC, and decrypt.
    """
    if not packets:
        return None, None

    # Group by CRC and pick the most redundant consistent set.
    by_crc: Dict[int, List[DecodedPacket]] = {}
    for p in packets:
        crc = int(p.header["crc32"])
        by_crc.setdefault(crc, []).append(p)

    # Choose the CRC group with most packets and full sequence coverage if possible.
    best_group: List[DecodedPacket] = []
    chosen_crc = None
    for crc, group in by_crc.items():
        idxs = {int(p.header["packet_index"]) for p in group}
        total_expected = max(int(p.header["total_packets"]) for p in group)
        if len(idxs) == total_expected and len(group) >= len(best_group):
            best_group = group
            chosen_crc = crc

    if not best_group:
        logger.error("No complete packet sets reconstructed")
        return None, None

    best_group.sort(key=lambda p: int(p.header["packet_index"]))
    concatenated_sonar_b64 = "".join(
        p.payload_fragment_sonar_b64 for p in best_group
    )
    blob = decode_base64_from_sonar(concatenated_sonar_b64)

    try:
        encrypted = EncryptedPayload.deserialize_compact(blob)
    except ValueError as e:
        logger.error("Failed to parse encrypted payload: %s", e)
        return None, None

    try:
        plaintext = decrypt_payload(password, encrypted)
    except Exception as e:
        logger.error("Decryption failed: %s", e)
        return None, None

    import zlib as _zlib

    crc_check = _zlib.crc32(blob + plaintext) & 0xFFFFFFFF
    if chosen_crc is not None and crc_check != chosen_crc:
        logger.error(
            "CRC mismatch: expected %08x, got %08x", chosen_crc, crc_check
        )
        return None, None

    # Return header from first packet for metadata.
    header = best_group[0].header
    return plaintext, header

