from __future__ import annotations

import json
import math
import zlib
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

import numpy as np

from config import audio_config, packet_config
from crypto import EncryptedPayload, encode_base64_for_sonar
from logging_utils import get_logger


logger = get_logger(__name__)


# Restricted alphabet for FSK symbols.
# We support the full visible ASCII range (space through ~) so that any
# JSON/base64 or user text used in headers/payload framing can be represented.
SONAR_ALPHABET = "".join(chr(c) for c in range(32, 127))

_char_to_symbol: Dict[str, int] = {ch: i for i, ch in enumerate(SONAR_ALPHABET)}
_symbol_to_char: Dict[int, str] = {i: ch for ch, i in _char_to_symbol.items()}


def validate_text_chars(text: str) -> None:
    invalid = sorted({ch for ch in text if ch not in _char_to_symbol})
    if invalid:
        raise ValueError(
            f"Text contains unsupported characters: {''.join(invalid)}"
        )


def text_to_symbols(text: str) -> List[int]:
    validate_text_chars(text)
    return [_char_to_symbol[ch] for ch in text]


def symbols_to_text(symbols: List[int]) -> str:
    return "".join(_symbol_to_char[s] for s in symbols)


def symbol_to_frequency(symbol: int, base_frequency_hz: float) -> float:
    return base_frequency_hz + audio_config.frequency_step_hz * float(symbol)


@dataclass
class PacketHeader:
    version: int
    message_type: str  # "text" | "coords" | "file"
    packet_index: int
    total_packets: int
    base_frequency_hz: float
    file_name: str | None
    file_size: int | None
    salt_b64: str
    iv_b64: str
    crc32: int


@dataclass
class Packet:
    header: PacketHeader
    payload_fragment_b64: str  # fragment of encrypted blob, sonar-safe b64

    def to_wire_text(self) -> str:
        obj = {
            "h": asdict(self.header),
            "p": self.payload_fragment_b64,
        }
        return json.dumps(obj, separators=(",", ":"))


def _compute_crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def build_packets(
    message_type: str,
    plaintext_payload: bytes,
    file_name: str | None,
    password: str,
    encrypted: EncryptedPayload,
    base_frequency_hz: float,
) -> List[Packet]:
    """
    Split encrypted payload into packets with metadata headers.
    """
    full_blob = encrypted.serialize_compact()
    crc_all = _compute_crc32(full_blob + plaintext_payload)

    file_size = len(plaintext_payload) if message_type == "file" else None

    # Convert full encrypted blob to sonar-safe base64 text.
    sonar_b64_full = encode_base64_for_sonar(full_blob)
    max_payload_chars = packet_config.max_payload_bytes
    fragments = [
        sonar_b64_full[i : i + max_payload_chars]
        for i in range(0, len(sonar_b64_full), max_payload_chars)
    ]

    total_packets = len(fragments)
    if total_packets == 0:
        total_packets = 1
        fragments = [""]

    salt_b64, iv_b64 = encrypted.to_header_fields()

    packets: List[Packet] = []
    for idx, fragment in enumerate(fragments):
        header = PacketHeader(
            version=1,
            message_type=message_type,
            packet_index=idx,
            total_packets=total_packets,
            base_frequency_hz=base_frequency_hz,
            file_name=file_name,
            file_size=file_size,
            salt_b64=salt_b64,
            iv_b64=iv_b64,
            crc32=crc_all,
        )
        packets.append(Packet(header=header, payload_fragment_b64=fragment))

    logger.info(
        "Built %d packets (type=%s, total_bytes=%d)",
        len(packets),
        message_type,
        len(full_blob),
    )
    return packets


def packet_to_waveform(packet: Packet) -> np.ndarray:
    """
    Convert a packet into a concatenated waveform of FSK tones.
    """
    wire_text = packet.to_wire_text()
    # Simple framing: prepend and append special markers.
    framed = f"::" + wire_text + "::"
    symbols = text_to_symbols(framed)

    sr = audio_config.sample_rate
    symbol_len = int(audio_config.symbol_duration_s * sr)
    silence_len = int(audio_config.inter_symbol_silence_s * sr)
    t = np.linspace(0, audio_config.symbol_duration_s, symbol_len, endpoint=False)

    base = packet.header.base_frequency_hz
    waveform_parts: List[np.ndarray] = []

    for s in symbols:
        freq = symbol_to_frequency(s, base)
        tone = np.sin(2.0 * math.pi * freq * t).astype(np.float32)
        waveform_parts.append(tone)
        if silence_len > 0:
            waveform_parts.append(np.zeros(silence_len, dtype=np.float32))

    waveform = np.concatenate(waveform_parts)
    # Normalize amplitude to avoid clipping.
    max_val = np.max(np.abs(waveform)) or 1.0
    waveform = (waveform / max_val * 0.8).astype(np.float32)
    return waveform


def get_alphabet() -> str:
    return SONAR_ALPHABET

