from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from config import audio_config
from crypto import encode_base64_for_sonar
from logging_utils import setup_logging, get_logger
from receiver import receive_and_decode, save_received_file
from transmitter import prepare_encrypted_packets, transmit_packets


logger = get_logger(__name__)


MessageMode = Literal["text", "coords", "file"]


def _build_plaintext_for_mode(
    mode: MessageMode,
    message: str | None,
    coords: str | None,
    file_path: Path | None,
) -> tuple[bytes, str | None]:
    if mode == "text":
        if not message:
            raise ValueError("Text mode requires --message")
        payload = message.upper().encode("utf-8")
        return payload, None
    if mode == "coords":
        if not coords:
            raise ValueError("Coords mode requires --coords")
        payload = coords.strip().encode("utf-8")
        return payload, None
    if mode == "file":
        if not file_path:
            raise ValueError("File mode requires --file-path")
        data = file_path.read_bytes()
        if len(data) > 10 * 1024:
            raise ValueError("File exceeds 10KB limit")
        return data, file_path.name
    raise ValueError(f"Unsupported mode {mode}")


def run_transmitter(args: argparse.Namespace) -> None:
    password = args.password
    mode: MessageMode = args.mode
    message = args.message
    coords = args.coords
    file_path = Path(args.file_path) if args.file_path else None

    plaintext, file_name = _build_plaintext_for_mode(
        mode=mode,
        message=message,
        coords=coords,
        file_path=file_path,
    )

    packets = prepare_encrypted_packets(
        message_type=mode,
        plaintext_payload=plaintext,
        password=password,
        file_name=file_name,
    )
    transmit_packets(packets)


def run_receiver(args: argparse.Namespace) -> None:
    password = args.password
    duration_s: float = args.listen_seconds
    mode: MessageMode = args.mode

    plaintext, header, peak_log = receive_and_decode(
        duration_s=duration_s,
        password=password,
    )

    for freq, conf in peak_log:
        logger.info("Detected freq=%.1f Hz, confidence=%.2f", freq, conf)

    if plaintext is None or header is None:
        logger.error("No valid payload reconstructed")
        return

    msg_type = header.get("message_type")
    if mode != "file" and msg_type == "file":
        logger.warning("Received file payload but running in non-file mode")

    if msg_type == "file":
        output_dir = Path(args.output_dir or ".")
        save_received_file(plaintext, header, output_dir=output_dir)
    else:
        try:
            text = plaintext.decode("utf-8", errors="replace")
        except Exception:
            text = encode_base64_for_sonar(plaintext)
        logger.info("Decrypted payload (%s): %s", msg_type, text)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sonar-Share: AI-Driven Acoustic Communication"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    tx = subparsers.add_parser("transmit", help="Run in transmitter mode")
    tx.add_argument(
        "--mode",
        choices=["text", "coords", "file"],
        required=True,
        help="Payload type",
    )
    tx.add_argument("--message", type=str, help="Text message for text mode")
    tx.add_argument(
        "--coords",
        type=str,
        help='Coordinates for coords mode (e.g., "28.6139,77.2090")',
    )
    tx.add_argument(
        "--file-path",
        type=str,
        help="Path to file (<10KB) for file mode",
    )
    tx.add_argument(
        "--password",
        type=str,
        required=True,
        help="Password for AES-256 encryption",
    )
    tx.set_defaults(func=run_transmitter)

    rx = subparsers.add_parser("receive", help="Run in receiver mode")
    rx.add_argument(
        "--mode",
        choices=["text", "coords", "file"],
        required=True,
        help="Expected payload type (affects handling/logging)",
    )
    rx.add_argument(
        "--listen-seconds",
        type=float,
        default=15.0,
        help="Duration to listen for incoming transmission",
    )
    rx.add_argument(
        "--password",
        type=str,
        required=True,
        help="Password for AES-256 decryption",
    )
    rx.add_argument(
        "--output-dir",
        type=str,
        help="Directory to store received files (file mode)",
    )
    rx.set_defaults(func=run_receiver)

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    setup_logging(debug=args.debug)
    logger.info("Audio sample rate: %d Hz", audio_config.sample_rate)
    args.func(args)


if __name__ == "__main__":
    main()

