from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import sounddevice as sd
from scipy.signal import get_window

from config import audio_config, ai_config
from logging_utils import get_logger


logger = get_logger(__name__)


@dataclass
class NoiseBand:
    center_hz: float
    magnitude: float


@dataclass
class NoiseProfile:
    dominant_bands: List[NoiseBand]


def analyze_ambient_noise(duration_s: float | None = None) -> NoiseProfile:
    """
    Capture ambient noise and estimate dominant bands in the target frequency range.
    """
    dur = duration_s or ai_config.pre_tx_noise_sample_s
    sr = audio_config.sample_rate
    logger.info("Sampling ambient noise for %.2fs", dur)
    data = sd.rec(int(dur * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    mono = data[:, 0]

    window = get_window(audio_config.fft_window, len(mono))
    windowed = mono * window
    spectrum = np.fft.rfft(windowed)
    freqs = np.fft.rfftfreq(len(windowed), d=1.0 / sr)
    mags = np.abs(spectrum)

    band_mask = (freqs >= audio_config.expected_band_low_hz) & (
        freqs <= audio_config.expected_band_high_hz
    )
    freqs_band = freqs[band_mask]
    mags_band = mags[band_mask]

    if freqs_band.size == 0:
        return NoiseProfile(dominant_bands=[])

    # Identify a few strongest peaks as dominant bands.
    n_peaks = min(5, freqs_band.size)
    idx_sorted = np.argsort(mags_band)[-n_peaks:]
    bands = [
        NoiseBand(center_hz=float(freqs_band[i]), magnitude=float(mags_band[i]))
        for i in idx_sorted
    ]
    logger.debug("Detected %d dominant noise bands", len(bands))
    return NoiseProfile(dominant_bands=bands)


def choose_base_frequency(
    noise_profile: NoiseProfile, num_symbols: int
) -> float:
    """
    Choose base frequency near configured base while avoiding dominant noise bands.
    """
    base = audio_config.base_frequency_hz
    step = audio_config.frequency_step_hz

    candidate_offsets = list(range(-5, 6))  # +/- up to 5 steps
    best_score = float("inf")
    best_base = base

    for offset in candidate_offsets:
        candidate_base = base + offset * step
        low = candidate_base
        high = candidate_base + step * (num_symbols - 1)
        if (
            low < audio_config.expected_band_low_hz
            or high > audio_config.expected_band_high_hz
        ):
            continue

        # Score candidate by overlap with dominant noise bands.
        score = 0.0
        for band in noise_profile.dominant_bands:
            margin = ai_config.noise_band_margin_hz
            if (band.center_hz + margin) >= low and (
                band.center_hz - margin
            ) <= high:
                score += band.magnitude

        if score < best_score:
            best_score = score
            best_base = candidate_base

    logger.info(
        "Selected base frequency %.1f Hz (score %.3f)", best_base, best_score
    )
    return best_base


@dataclass
class ThresholdState:
    noise_floor_history: List[float]

    def update(
        self, peak_magnitude: float, band_magnitudes: np.ndarray
    ) -> Tuple[float, float, bool]:
        """
        Update rolling noise floor and compute adaptive threshold and confidence.

        Returns: (threshold, confidence, accepted)
        """
        # Estimate noise floor as median of band magnitudes.
        if band_magnitudes.size > 0:
            noise_floor = float(np.median(band_magnitudes))
        else:
            noise_floor = 0.0

        self.noise_floor_history.append(noise_floor)
        if len(self.noise_floor_history) > ai_config.rolling_window_symbols:
            self.noise_floor_history.pop(0)

        rolling_floor = (
            float(np.mean(self.noise_floor_history))
            if self.noise_floor_history
            else noise_floor
        )
        if rolling_floor <= 0:
            rolling_floor = max(noise_floor, 1e-9)

        confidence = peak_magnitude / rolling_floor
        threshold = ai_config.min_confidence
        accepted = confidence >= threshold
        logger.debug(
            "Peak=%.4f, floor=%.4f, conf=%.3f, accepted=%s",
            peak_magnitude,
            rolling_floor,
            confidence,
            accepted,
        )
        return threshold, confidence, accepted


def create_threshold_state() -> ThresholdState:
    return ThresholdState(noise_floor_history=[])

