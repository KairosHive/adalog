"""
HuggingFace Upload Panel for Adalog Sense
Allows users to select and upload sessions to HuggingFace datasets.
"""

import os
from pathlib import Path
from typing import List, Set
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QCheckBox, QScrollArea, QFrame, QMessageBox,
    QGroupBox, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


class UploadWorker(QThread):
    """Background thread for uploading to HuggingFace."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, sessions_dir, repo_id, token, selected_users, selected_sessions, selected_modalities):
        super().__init__()
        self.sessions_dir = sessions_dir
        self.repo_id = repo_id
        self.token = token
        self.selected_users = selected_users
        self.selected_sessions = selected_sessions
        self.selected_modalities = selected_modalities
    
    def run(self):
        try:
            from adalog.upload_to_hf import AdalogDatasetUploader
            
            # Set token in environment
            os.environ["HF_TOKEN"] = self.token
            
            self.progress.emit("Initializing uploader...")
            uploader = AdalogDatasetUploader(
                sessions_dir=self.sessions_dir,
                repo_id=self.repo_id,
                use_cache=True
            )
            
            # Use the proper create_and_upload which handles merging
            if self.selected_users:
                self.progress.emit(f"Uploading sessions for: {', '.join(self.selected_users)}")
                
                uploader.create_and_upload(
                    repo_id=self.repo_id,
                    private=False,
                    force_reupload=False,
                    filter_users=self.selected_users
                )
                
                self.finished.emit(True, f"Successfully uploaded sessions for {', '.join(self.selected_users)}!")
            else:
                self.finished.emit(False, "No users selected")
                return
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Upload error:\n{error_details}")
            self.finished.emit(False, f"Error: {str(e)}")


class HuggingFaceUploadPanel(QWidget):
    """Collapsible panel for uploading sessions to HuggingFace."""
    
    def __init__(self, sessions_dir: str = "sessions", default_repo_id: str = ""):
        super().__init__()
        self.sessions_dir = sessions_dir
        self.default_repo_id = default_repo_id
        self.is_expanded = False
        self.upload_worker = None
        
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Header with toggle button
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header_layout = QHBoxLayout(header)
        
        self.toggle_btn = QPushButton("▶ HuggingFace Upload")
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 5px;
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #4a4a4a;
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_panel)
        header_layout.addWidget(self.toggle_btn)
        
        main_layout.addWidget(header)
        
        # Content panel (collapsible)
        self.content = QWidget()
        self.content.setVisible(False)
        content_layout = QVBoxLayout(self.content)
        content_layout.setSpacing(10)
        
        # Credentials section
        creds_group = QGroupBox("Credentials")
        creds_layout = QVBoxLayout()
        
        # HF Token
        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel("HF Token:"))
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("Enter your HuggingFace token")
        token_layout.addWidget(self.token_input)
        creds_layout.addLayout(token_layout)
        
        # Repo ID (public)
        repo_layout = QHBoxLayout()
        repo_layout.addWidget(QLabel("Repo ID:"))
        self.repo_input = QLineEdit()
        self.repo_input.setText(self.default_repo_id)
        self.repo_input.setPlaceholderText("username/dataset-name")
        repo_layout.addWidget(self.repo_input)
        creds_layout.addLayout(repo_layout)
        
        creds_group.setLayout(creds_layout)
        content_layout.addWidget(creds_group)
        
        # Selection section
        selection_group = QGroupBox("Selection")
        selection_layout = QVBoxLayout()
        
        # Users selection
        users_label = QLabel("Select Users:")
        selection_layout.addWidget(users_label)
        
        self.users_scroll = QScrollArea()
        self.users_scroll.setMaximumHeight(100)
        self.users_widget = QWidget()
        self.users_layout = QVBoxLayout(self.users_widget)
        self.users_layout.setSpacing(2)
        self.users_checkboxes = {}
        self.users_scroll.setWidget(self.users_widget)
        self.users_scroll.setWidgetResizable(True)
        selection_layout.addWidget(self.users_scroll)
        
        # Refresh users button
        refresh_btn = QPushButton("Refresh Users")
        refresh_btn.clicked.connect(self.load_users)
        selection_layout.addWidget(refresh_btn)
        
        # Modalities selection
        modalities_label = QLabel("Select Modalities:")
        selection_layout.addWidget(modalities_label)
        
        modalities_layout = QHBoxLayout()
        self.modality_checkboxes = {}
        for modality in ["Eeg", "Ecg", "Audio", "Text", "Meteo", "Osc", "Drawing"]:
            cb = QCheckBox(modality)
            cb.setChecked(True)
            self.modality_checkboxes[modality] = cb
            modalities_layout.addWidget(cb)
        selection_layout.addLayout(modalities_layout)
        
        # Select all/none buttons
        select_btns = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_modalities)
        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(self.select_no_modalities)
        select_btns.addWidget(select_all_btn)
        select_btns.addWidget(select_none_btn)
        select_btns.addStretch()
        selection_layout.addLayout(select_btns)
        
        selection_group.setLayout(selection_layout)
        content_layout.addWidget(selection_group)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        content_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        content_layout.addWidget(self.status_label)
        
        # Upload button
        buttons_layout = QHBoxLayout()
        
        self.upload_btn = QPushButton("Upload to HuggingFace")
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background: #2ea44f;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2c974b;
            }
            QPushButton:disabled {
                background: #555;
                color: #888;
            }
        """)
        self.upload_btn.clicked.connect(self.start_upload)
        buttons_layout.addWidget(self.upload_btn)
        
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setStyleSheet("""
            QPushButton {
                background: #d73a49;
                color: white;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #cb2431;
            }
        """)
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        buttons_layout.addWidget(self.clear_cache_btn)
        
        content_layout.addLayout(buttons_layout)
        
        main_layout.addWidget(self.content)
        
        # Load users initially
        self.load_users()
    
    def toggle_panel(self):
        """Toggle the visibility of the content panel."""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.toggle_btn.setText("▼ HuggingFace Upload" if self.is_expanded else "▶ HuggingFace Upload")
    
    def load_users(self):
        """Scan and load available users from sessions directory."""
        # Clear existing checkboxes
        for cb in self.users_checkboxes.values():
            cb.deleteLater()
        self.users_checkboxes.clear()
        
        # Scan users
        sessions_path = Path(self.sessions_dir)
        if not sessions_path.exists():
            self.status_label.setText("Sessions directory not found")
            return
        
        users = []
        for user_dir in sessions_path.iterdir():
            if user_dir.is_dir():
                users.append(user_dir.name)
        
        users.sort()
        
        # Create checkboxes
        for user in users:
            cb = QCheckBox(user)
            cb.setChecked(True)
            self.users_checkboxes[user] = cb
            self.users_layout.addWidget(cb)
        
        if not users:
            self.status_label.setText("No users found in sessions directory")
        else:
            self.status_label.setText(f"Found {len(users)} user(s)")
    
    def clear_cache(self):
        """Clear the upload cache file."""
        cache_file = Path(".hf_upload_cache.json")
        if cache_file.exists():
            try:
                cache_file.unlink()
                self.status_label.setText("✓ Cache cleared successfully")
            except Exception as e:
                self.status_label.setText(f"❌ Error clearing cache: {str(e)}")
        else:
            self.status_label.setText("ℹ️ No cache file found")
    
    def select_all_modalities(self):
        """Select all modality checkboxes."""
        for cb in self.modality_checkboxes.values():
            cb.setChecked(True)
    
    def select_no_modalities(self):
        """Deselect all modality checkboxes."""
        for cb in self.modality_checkboxes.values():
            cb.setChecked(False)
    
    def start_upload(self):
        """Start the upload process."""
        # Validate inputs
        token = self.token_input.text().strip()
        repo_id = self.repo_input.text().strip()
        
        if not token:
            QMessageBox.warning(self, "Missing Token", "Please enter your HuggingFace token")
            return
        
        if not repo_id:
            QMessageBox.warning(self, "Missing Repo ID", "Please enter a repository ID")
            return
        
        # Get selected users
        selected_users = [user for user, cb in self.users_checkboxes.items() if cb.isChecked()]
        if not selected_users:
            QMessageBox.warning(self, "No Users", "Please select at least one user")
            return
        
        # Get selected modalities
        selected_modalities = [mod for mod, cb in self.modality_checkboxes.items() if cb.isChecked()]
        
        # Confirm upload
        msg = f"Upload {len(selected_users)} users ({', '.join(selected_users)})"
        if selected_modalities:
            msg += f" with {len(selected_modalities)} modalities"
        msg += f" to {repo_id}?"
        msg += "\n\n⚠️ This will merge with existing data online (no duplicates)."
        
        reply = QMessageBox.question(
            self, "Confirm Upload", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Disable UI during upload
        self.upload_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Starting upload...")
        
        # Start upload in background thread
        self.upload_worker = UploadWorker(
            self.sessions_dir,
            repo_id,
            token,
            selected_users,
            [],  # All sessions for selected users
            selected_modalities
        )
        self.upload_worker.progress.connect(self.on_progress)
        self.upload_worker.finished.connect(self.on_finished)
        self.upload_worker.start()
    
    def on_progress(self, message: str):
        """Update progress status."""
        self.status_label.setText(message)
    
    def on_finished(self, success: bool, message: str):
        """Handle upload completion."""
        self.upload_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)
        
        if success:
            QMessageBox.information(self, "Upload Complete", message)
        else:
            QMessageBox.critical(self, "Upload Failed", message)
