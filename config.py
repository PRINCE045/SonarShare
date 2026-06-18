from __future__ import annotations

"""
Global configuration values for Sonar-Share.

Centralizing these makes it easier to tune and extend the system without
coupling modules tightly together.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 44_100
    symbol_duration_s: float = 0.08  # per-tone duration
    inter_symbol_silence_s: float = 0.015
    base_frequency_hz: float = 9_000.0
    frequency_step_hz: float = 200.0
    max_symbols: int = 128  # room to expand mapping
    fft_window: str = "hamming"
    expected_band_low_hz: float = 7_000.0
    expected_band_high_hz: float = 11_000.0
    detection_tolerance_hz: float = 100.0


@dataclass(frozen=True)
class CryptoConfig:
    key_length_bits: int = 256
    pbkdf2_iterations: int = 200_000
    salt_length_bytes: int = 16
    iv_length_bytes: int = 16


@dataclass(frozen=True)
class PacketConfig:
    max_payload_bytes: int = 9_000  # under 10 KB including overhead
    redundancy_copies: int = 2  # simple redundancy for error mitigation


@dataclass(frozen=True)
class AIConfig:
    pre_tx_noise_sample_s: float = 0.5
    noise_band_margin_hz: float = 300.0
    min_confidence: float = 2.0  # ratio between peak and noise floor
    rolling_window_symbols: int = 10


audio_config = AudioConfig()
crypto_config = CryptoConfig()
packet_config = PacketConfig()
ai_config = AIConfig()

