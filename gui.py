"""
Sonar-Share GUI - Professional Desktop Application

This module provides a PyQt6-based GUI that integrates with the existing
backend modules (transmitter, receiver, crypto, encoder, decoder, ai_engine).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QLabel,
    QFileDialog,
    QLineEdit,
    QGroupBox,
    QScrollArea,
    QMessageBox,
    QSplitter,
    QFrame,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
)

# Backend imports - DO NOT duplicate logic
from config import audio_config, packet_config, ai_config, crypto_config
from transmitter import prepare_encrypted_packets, transmit_packets
from receiver import receive_and_decode, save_received_file
from ai_engine import analyze_ambient_noise, choose_base_frequency
from logging_utils import setup_logging, get_logger

logger = get_logger(__name__)
setup_logging(debug=False)


class ReceiveThread(QThread):
    """Thread for receiving audio without blocking GUI."""
    
    finished = pyqtSignal(bytes, dict, list)  # plaintext, header, peak_log
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)
    
    def __init__(self, duration_s: float, password: str):
        super().__init__()
        self.duration_s = duration_s
        self.password = password
        self._stop_requested = False
    
    def run(self):
        try:
            self.status_update.emit("Recording audio...")
            plaintext, header, peak_log = receive_and_decode(
                duration_s=self.duration_s,
                password=self.password,
            )
            if plaintext is None:
                self.error.emit("No valid payload detected. Check password and ensure transmission is active.")
            else:
                self.finished.emit(plaintext, header or {}, peak_log)
        except Exception as e:
            self.error.emit(f"Receive error: {str(e)}")
    
    def stop(self):
        self._stop_requested = True


class SonarShareGUI(QMainWindow):
    """Main GUI window for Sonar-Share."""
    
    def __init__(self):
        super().__init__()
        self.receive_thread: Optional[ReceiveThread] = None
        self.password = ""
        self.init_ui()
        self.apply_dark_theme()
    
    def init_ui(self):
        self.setWindowTitle("Sonar-Share – AI Air-Gapped Communication")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Main splitter: Left (Send) | Right (Receive)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Send
        send_panel = self.create_send_panel()
        splitter.addWidget(send_panel)
        
        # Right panel - Receive
        receive_panel = self.create_receive_panel()
        splitter.addWidget(receive_panel)
        
        splitter.setSizes([700, 700])
        main_layout.addWidget(splitter)
        
        # Status/Logs panel at bottom
        logs_panel = self.create_logs_panel()
        main_layout.addWidget(logs_panel)
        
        # Status indicators
        status_bar = self.create_status_bar()
        main_layout.addWidget(status_bar)
    
    def create_header(self) -> QWidget:
        """Create header section with title."""
        header = QFrame()
        header.setFixedHeight(60)
        layout = QHBoxLayout(header)
        
        title = QLabel("Sonar-Share")
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #4CAF50;")
        
        subtitle = QLabel("AI-Driven Air-Gapped Acoustic Communication System")
        subtitle_font = QFont("Segoe UI", 10)
        subtitle.setFont(subtitle_font)
        subtitle.setStyleSheet("color: #B0BEC5;")
        
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch()
        
        return header
    
    def create_send_panel(self) -> QWidget:
        """Create left panel for sending data."""
        panel = QGroupBox("📤 Send Mode")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # Password input
        password_group = QHBoxLayout()
        password_label = QLabel("Encryption Password:")
        password_label.setFixedWidth(150)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter password for AES-256 encryption")
        self.password_input.textChanged.connect(self.on_password_changed)
        password_group.addWidget(password_label)
        password_group.addWidget(self.password_input)
        layout.addLayout(password_group)
        
        # Text input
        text_label = QLabel("Text Message:")
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Enter your message here...")
        self.text_input.setMaximumHeight(120)
        layout.addWidget(text_label)
        layout.addWidget(self.text_input)
        
        # Coordinates input
        coords_group = QHBoxLayout()
        coords_label = QLabel("Coordinates:")
        self.coords_input = QLineEdit()
        self.coords_input.setPlaceholderText("e.g., 28.6139,77.2090")
        coords_group.addWidget(coords_label)
        coords_group.addWidget(self.coords_input)
        layout.addLayout(coords_group)
        
        # File selection
        file_group = QHBoxLayout()
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setStyleSheet("color: #90A4AE; font-style: italic;")
        file_btn = QPushButton("📁 Select File")
        file_btn.clicked.connect(self.select_file)
        file_group.addWidget(QLabel("File:"))
        file_group.addWidget(self.file_path_label)
        file_group.addWidget(file_btn)
        layout.addLayout(file_group)
        
        self.selected_file_path: Optional[Path] = None
        
        # Encryption status
        self.encryption_status = QLabel("Encryption: Not Ready")
        self.encryption_status.setStyleSheet("color: #FF9800; font-weight: bold;")
        layout.addWidget(self.encryption_status)
        
        # Send buttons
        button_layout = QHBoxLayout()
        self.send_text_btn = QPushButton("📤 Send Text")
        self.send_text_btn.clicked.connect(lambda: self.send_data("text"))
        self.send_coords_btn = QPushButton("📍 Send Coordinates")
        self.send_coords_btn.clicked.connect(lambda: self.send_data("coords"))
        self.send_file_btn = QPushButton("📎 Send File")
        self.send_file_btn.clicked.connect(lambda: self.send_data("file"))
        
        button_layout.addWidget(self.send_text_btn)
        button_layout.addWidget(self.send_coords_btn)
        button_layout.addWidget(self.send_file_btn)
        layout.addLayout(button_layout)
        
        # Transmission info
        self.transmission_info = QLabel("")
        self.transmission_info.setStyleSheet("color: #81C784; font-size: 10pt;")
        self.transmission_info.setWordWrap(True)
        layout.addWidget(self.transmission_info)
        
        layout.addStretch()
        return panel
    
    def create_receive_panel(self) -> QWidget:
        """Create right panel for receiving data."""
        panel = QGroupBox("📥 Receive Mode")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # Listen duration
        duration_group = QHBoxLayout()
        duration_label = QLabel("Listen Duration (seconds):")
        self.listen_duration = QSpinBox()
        self.listen_duration.setMinimum(5)
        self.listen_duration.setMaximum(120)
        self.listen_duration.setValue(15)
        duration_group.addWidget(duration_label)
        duration_group.addWidget(self.listen_duration)
        layout.addLayout(duration_group)
        
        # Receive buttons
        button_layout = QHBoxLayout()
        self.start_listen_btn = QPushButton("▶ Start Listening")
        self.start_listen_btn.clicked.connect(self.start_receiving)
        self.stop_listen_btn = QPushButton("⏹ Stop Listening")
        self.stop_listen_btn.clicked.connect(self.stop_receiving)
        self.stop_listen_btn.setEnabled(False)
        button_layout.addWidget(self.start_listen_btn)
        button_layout.addWidget(self.stop_listen_btn)
        layout.addLayout(button_layout)
        
        # Output display
        output_label = QLabel("Decrypted Output:")
        self.output_display = QTextEdit()
        self.output_display.setReadOnly(True)
        self.output_display.setPlaceholderText("Received data will appear here...")
        layout.addWidget(output_label)
        layout.addWidget(self.output_display)
        
        # Confidence and frequency display
        metrics_layout = QVBoxLayout()
        
        self.confidence_label = QLabel("Signal Confidence: --")
        self.confidence_label.setStyleSheet("color: #64B5F6; font-weight: bold;")
        metrics_layout.addWidget(self.confidence_label)
        
        self.frequency_label = QLabel("Detected Frequency: -- Hz")
        self.frequency_label.setStyleSheet("color: #64B5F6; font-weight: bold;")
        metrics_layout.addWidget(self.frequency_label)
        
        self.decryption_status = QLabel("Decryption: Waiting...")
        self.decryption_status.setStyleSheet("color: #FF9800; font-weight: bold;")
        metrics_layout.addWidget(self.decryption_status)
        
        layout.addLayout(metrics_layout)
        layout.addStretch()
        return panel
    
    def create_logs_panel(self) -> QWidget:
        """Create logs/status panel."""
        panel = QGroupBox("📋 Logs & Status")
        layout = QVBoxLayout(panel)
        
        self.logs_display = QTextEdit()
        self.logs_display.setReadOnly(True)
        self.logs_display.setMaximumHeight(150)
        self.logs_display.setFont(QFont("Consolas", 9))
        layout.addWidget(self.logs_display)
        
        return panel
    
    def create_status_bar(self) -> QWidget:
        """Create status bar with AI, security, and transmission info."""
        status_frame = QFrame()
        status_frame.setFixedHeight(80)
        layout = QHBoxLayout(status_frame)
        layout.setSpacing(20)
        
        # AI Status
        ai_group = QVBoxLayout()
        ai_title = QLabel("🧠 AI Engine")
        ai_title.setStyleSheet("font-weight: bold; color: #4CAF50;")
        self.noise_label = QLabel("Noise: Analyzing...")
        self.adaptive_label = QLabel("Adaptive Mode: ON")
        self.threshold_label = QLabel("Threshold: --")
        ai_group.addWidget(ai_title)
        ai_group.addWidget(self.noise_label)
        ai_group.addWidget(self.adaptive_label)
        ai_group.addWidget(self.threshold_label)
        layout.addLayout(ai_group)
        
        # Security Status
        security_group = QVBoxLayout()
        security_title = QLabel("🔐 Security")
        security_title.setStyleSheet("font-weight: bold; color: #FF9800;")
        self.aes_label = QLabel(f"Encryption: AES-{crypto_config.key_length_bits}")
        self.error_correction_label = QLabel(f"Error Correction: Active ({packet_config.redundancy_copies}x)")
        self.airgap_label = QLabel("Air-Gap Mode: Active")
        security_group.addWidget(security_title)
        security_group.addWidget(self.aes_label)
        security_group.addWidget(self.error_correction_label)
        security_group.addWidget(self.airgap_label)
        layout.addLayout(security_group)
        
        # Transmission Settings (collapsible info)
        settings_group = QVBoxLayout()
        settings_title = QLabel("⚙️ Transmission Settings")
        settings_title.setStyleSheet("font-weight: bold; color: #64B5F6;")
        self.base_freq_label = QLabel(f"Base Frequency: {audio_config.base_frequency_hz:.0f} Hz")
        self.freq_step_label = QLabel(f"Frequency Step: {audio_config.frequency_step_hz:.0f} Hz")
        self.sample_rate_label = QLabel(f"Sample Rate: {audio_config.sample_rate} Hz")
        settings_group.addWidget(settings_title)
        settings_group.addWidget(self.base_freq_label)
        settings_group.addWidget(self.freq_step_label)
        settings_group.addWidget(self.sample_rate_label)
        layout.addLayout(settings_group)
        
        layout.addStretch()
        return status_frame
    
    def apply_dark_theme(self):
        """Apply dark theme styling."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #263238;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #546E7A;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #37474F;
                color: #ECEFF1;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #546E7A;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #607D8B;
            }
            QPushButton:pressed {
                background-color: #455A64;
            }
            QPushButton:disabled {
                background-color: #37474F;
                color: #90A4AE;
            }
            QTextEdit, QLineEdit {
                background-color: #455A64;
                color: #ECEFF1;
                border: 1px solid #546E7A;
                border-radius: 3px;
                padding: 5px;
            }
            QLabel {
                color: #ECEFF1;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #455A64;
                color: #ECEFF1;
                border: 1px solid #546E7A;
                border-radius: 3px;
                padding: 3px;
            }
        """)
    
    def on_password_changed(self, text: str):
        """Update password when input changes."""
        self.password = text
        if text:
            self.encryption_status.setText("Encryption: Ready (AES-256)")
            self.encryption_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.encryption_status.setText("Encryption: Not Ready")
            self.encryption_status.setStyleSheet("color: #FF9800; font-weight: bold;")
    
    def select_file(self):
        """Open file dialog to select file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select File to Send",
            "",
            "All Files (*.*)"
        )
        if file_path:
            self.selected_file_path = Path(file_path)
            file_size = self.selected_file_path.stat().st_size
            if file_size > 10 * 1024:
                QMessageBox.warning(
                    self,
                    "File Too Large",
                    f"File size ({file_size / 1024:.1f} KB) exceeds 10 KB limit.\n"
                    "Please select a smaller file."
                )
                self.selected_file_path = None
                self.file_path_label.setText("No file selected")
            else:
                self.file_path_label.setText(f"{self.selected_file_path.name} ({file_size} bytes)")
                self.file_path_label.setStyleSheet("color: #4CAF50;")
    
    def send_data(self, mode: str):
        """Send data using backend transmitter."""
        if not self.password:
            QMessageBox.warning(self, "Password Required", "Please enter encryption password.")
            return
        
        try:
            # Prepare payload based on mode
            if mode == "text":
                text = self.text_input.toPlainText().strip()
                if not text:
                    QMessageBox.warning(self, "No Text", "Please enter a message to send.")
                    return
                payload = text.encode("utf-8")
                file_name = None
            elif mode == "coords":
                coords = self.coords_input.text().strip()
                if not coords:
                    QMessageBox.warning(self, "No Coordinates", "Please enter coordinates.")
                    return
                payload = coords.encode("utf-8")
                file_name = None
            elif mode == "file":
                if not self.selected_file_path or not self.selected_file_path.exists():
                    QMessageBox.warning(self, "No File", "Please select a file to send.")
                    return
                payload = self.selected_file_path.read_bytes()
                file_name = self.selected_file_path.name
            else:
                return
            
            # Disable buttons during transmission
            self.set_send_buttons_enabled(False)
            self.transmission_info.setText("Preparing transmission...")
            self.log_message(f"[SEND] Preparing {mode} transmission...")
            
            # Prepare encrypted packets using backend (handles noise analysis + encryption)
            self.log_message("[AI] Analyzing ambient noise and preparing packets...")
            packets = prepare_encrypted_packets(
                message_type=mode,
                plaintext_payload=payload,
                password=self.password,
                file_name=file_name,
            )
            
            # Extract base frequency and update AI status from prepared packets
            if packets:
                base_freq = packets[0].header.base_frequency_hz
                self.base_freq_label.setText(f"Base Frequency: {base_freq:.1f} Hz")
                self.threshold_label.setText(f"Threshold: {ai_config.min_confidence:.1f}x")
                self.noise_label.setText("Noise: Analyzed")
            
            # Transmit using backend
            self.log_message(f"[SEND] Transmitting {len(packets)} packet(s)...")
            self.transmission_info.setText(
                f"Transmitting...\n"
                f"Frequency: {base_freq:.1f} Hz\n"
                f"Packets: {len(packets)}\n"
                f"Encryption: AES-256 Active"
            )
            
            transmit_packets(packets)
            
            # Success
            self.log_message("[SEND] Transmission complete!")
            self.transmission_info.setText(
                f"✓ Transmission Complete\n"
                f"Mode: {mode.upper()}\n"
                f"Frequency: {base_freq:.1f} Hz\n"
                f"Encryption: AES-256 ✓"
            )
            
        except Exception as e:
            error_msg = f"Transmission error: {str(e)}"
            self.log_message(f"[ERROR] {error_msg}")
            QMessageBox.critical(self, "Transmission Failed", error_msg)
        finally:
            self.set_send_buttons_enabled(True)
    
    def set_send_buttons_enabled(self, enabled: bool):
        """Enable/disable send buttons."""
        self.send_text_btn.setEnabled(enabled)
        self.send_coords_btn.setEnabled(enabled)
        self.send_file_btn.setEnabled(enabled)
    
    def start_receiving(self):
        """Start receiving in background thread."""
        if not self.password:
            QMessageBox.warning(self, "Password Required", "Please enter encryption password.")
            return
        
        if self.receive_thread and self.receive_thread.isRunning():
            QMessageBox.warning(self, "Already Listening", "Receive operation already in progress.")
            return
        
        duration = self.listen_duration.value()
        self.log_message(f"[RECEIVE] Starting to listen for {duration} seconds...")
        self.decryption_status.setText("Decryption: Listening...")
        self.output_display.clear()
        
        # Disable start, enable stop
        self.start_listen_btn.setEnabled(False)
        self.stop_listen_btn.setEnabled(True)
        
        # Start thread
        self.receive_thread = ReceiveThread(duration, self.password)
        self.receive_thread.finished.connect(self.on_receive_finished)
        self.receive_thread.error.connect(self.on_receive_error)
        self.receive_thread.status_update.connect(self.log_message)
        self.receive_thread.start()
    
    def stop_receiving(self):
        """Stop receiving (if possible)."""
        if self.receive_thread and self.receive_thread.isRunning():
            self.receive_thread.terminate()
            self.receive_thread.wait()
        self.start_listen_btn.setEnabled(True)
        self.stop_listen_btn.setEnabled(False)
        self.decryption_status.setText("Decryption: Stopped")
        self.log_message("[RECEIVE] Stopped by user")
    
    def on_receive_finished(self, plaintext: bytes, header: dict, peak_log: list):
        """Handle successful receive."""
        self.start_listen_btn.setEnabled(True)
        self.stop_listen_btn.setEnabled(False)
        
        # Update confidence and frequency from peak_log
        if peak_log:
            avg_conf = sum(c for _, c in peak_log) / len(peak_log) if peak_log else 0
            avg_freq = sum(f for f, _ in peak_log) / len(peak_log) if peak_log else 0
            self.confidence_label.setText(f"Signal Confidence: {avg_conf:.2f}x")
            self.frequency_label.setText(f"Detected Frequency: {avg_freq:.1f} Hz")
        else:
            self.confidence_label.setText("Signal Confidence: --")
            self.frequency_label.setText("Detected Frequency: -- Hz")
        
        # Display decrypted output
        msg_type = header.get("message_type", "unknown")
        
        if msg_type == "file":
            # Save file
            try:
                output_dir = Path("received_files")
                saved_path = save_received_file(plaintext, header, output_dir)
                self.output_display.setText(
                    f"✓ File Received Successfully\n\n"
                    f"File: {saved_path.name}\n"
                    f"Size: {len(plaintext)} bytes\n"
                    f"Saved to: {saved_path}\n\n"
                    f"File content (first 500 bytes):\n"
                    f"{plaintext[:500]}"
                )
                self.log_message(f"[RECEIVE] File saved to {saved_path}")
            except Exception as e:
                self.output_display.setText(f"Error saving file: {str(e)}")
                self.log_message(f"[ERROR] File save failed: {e}")
        else:
            # Display text/coords
            try:
                text = plaintext.decode("utf-8", errors="replace")
                self.output_display.setText(f"✓ Decrypted {msg_type.upper()}\n\n{text}")
                self.log_message(f"[RECEIVE] Decrypted {msg_type}: {text[:50]}...")
            except Exception:
                self.output_display.setText(f"Binary data received:\n{plaintext.hex()[:200]}...")
        
        self.decryption_status.setText("Decryption: Success ✓")
        self.decryption_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
    
    def on_receive_error(self, error_msg: str):
        """Handle receive error."""
        self.start_listen_btn.setEnabled(True)
        self.stop_listen_btn.setEnabled(False)
        self.decryption_status.setText("Decryption: Failed")
        self.decryption_status.setStyleSheet("color: #F44336; font-weight: bold;")
        self.output_display.setText(f"✗ Error: {error_msg}")
        self.log_message(f"[ERROR] {error_msg}")
        QMessageBox.warning(self, "Receive Failed", error_msg)
    
    def log_message(self, message: str):
        """Add message to logs display."""
        timestamp = time.strftime("%H:%M:%S")
        self.logs_display.append(f"[{timestamp}] {message}")
        # Auto-scroll to bottom
        cursor = self.logs_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.logs_display.setTextCursor(cursor)


def main():
    """Launch GUI application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Modern look
    
    window = SonarShareGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
