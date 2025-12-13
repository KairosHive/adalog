"""
Upload Adalog sessions to Hugging Face as a dataset.

This script scans all session data from multiple users and uploads them
to Hugging Face Hub as a structured dataset.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime

import pandas as pd
from datasets import Dataset, DatasetDict, Features, Value, Audio, Sequence, concatenate_datasets
from huggingface_hub import HfApi, login

# Try to load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, will use system env vars only


class UploadCache:
    """Track which sessions have been uploaded to avoid re-uploading."""
    
    def __init__(self, cache_file: str = ".hf_upload_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache: Dict[str, Dict] = self._load_cache()
    
    def _load_cache(self) -> Dict[str, Dict]:
        """Load cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save cache to file."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")
    
    def get_session_hash(self, session_dir: Path) -> str:
        """Generate a hash representing the session's current state."""
        import hashlib
        
        hash_data = []
        
        # Include modification times of all files
        if session_dir.exists():
            for file_path in sorted(session_dir.rglob("*")):
                if file_path.is_file():
                    stat = file_path.stat()
                    hash_data.append(f"{file_path.name}:{stat.st_mtime}:{stat.st_size}")
        
        combined = "|".join(hash_data)
        return hashlib.md5(combined.encode()).hexdigest()
    
    def is_uploaded(self, user: str, session_id: str, session_dir: Path) -> bool:
        """Check if a session has been uploaded and hasn't changed."""
        key = f"{user}/{session_id}"
        if key not in self.cache:
            return False
        
        cached_hash = self.cache[key].get("hash")
        current_hash = self.get_session_hash(session_dir)
        
        return cached_hash == current_hash
    
    def mark_uploaded(self, user: str, session_id: str, session_dir: Path):
        """Mark a session as uploaded."""
        key = f"{user}/{session_id}"
        self.cache[key] = {
            "hash": self.get_session_hash(session_dir),
            "uploaded_at": datetime.now().isoformat()
        }
        self._save_cache()
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        return {
            "total_cached": len(self.cache),
            "cache_file": str(self.cache_file)
        }


class AdalogDatasetUploader:
    """Handles uploading Adalog session data to Hugging Face."""
    
    def __init__(self, sessions_dir: str = "sessions", repo_id: Optional[str] = None, use_cache: bool = True):
        """
        Initialize the uploader.
        
        Args:
            sessions_dir: Path to the sessions directory
            repo_id: Hugging Face repo ID (e.g., "username/adalog-sessions")
            use_cache: Whether to use caching to avoid re-uploading unchanged sessions
        """
        self.sessions_dir = Path(sessions_dir)
        self.repo_id = repo_id
        self.api = HfApi()
        self.use_cache = use_cache
        self.cache = UploadCache() if use_cache else None
        
    def scan_sessions(self, skip_cached: bool = True) -> List[Dict]:
        """
        Scan all sessions and extract metadata.
        
        Args:
            skip_cached: If True, skip sessions that haven't changed since last upload
        
        Returns:
            List of session dictionaries with metadata and file paths
        """
        sessions = []
        skipped_count = 0
        
        if not self.sessions_dir.exists():
            print(f"Sessions directory not found: {self.sessions_dir}")
            return sessions
        
        # Iterate through users
        for user_dir in self.sessions_dir.iterdir():
            if not user_dir.is_dir():
                continue
                
            user_name = user_dir.name
            
            # Iterate through sessions for this user
            for session_dir in user_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                    
                session_id = session_dir.name
                
                # Check cache if enabled
                if skip_cached and self.use_cache and self.cache.is_uploaded(user_name, session_id, session_dir):
                    skipped_count += 1
                    continue
                
                # Extract session data
                session_data = self._extract_session_data(
                    session_dir, user_name, session_id
                )
                
                if session_data:
                    sessions.append(session_data)
        
        total = len(sessions) + skipped_count
        print(f"Found {total} total sessions: {len(sessions)} new/changed, {skipped_count} unchanged (cached)")
        return sessions
    
    def _extract_session_data(
        self, session_dir: Path, user_name: str, session_id: str
    ) -> Optional[Dict]:
        """
        Extract data from a single session directory.
        
        Args:
            session_dir: Path to session directory
            user_name: Name of the user
            session_id: Session timestamp ID
            
        Returns:
            Dictionary with session data or None if invalid
        """
        session_data = {
            "user": user_name,
            "session_id": session_id,
            "session_datetime": session_id,  # ISO format timestamp
        }
        
        # Check for tags.csv
        tags_file = session_dir / "tags.csv"
        if tags_file.exists():
            try:
                tags_df = pd.read_csv(tags_file)
                if not tags_df.empty:
                    session_data["timestamp"] = tags_df["timestamp"].iloc[0]
                    session_data["tags"] = tags_df["tags"].iloc[0] if "tags" in tags_df.columns else ""
            except Exception as e:
                print(f"Error reading tags from {tags_file}: {e}")
                session_data["tags"] = ""
        else:
            session_data["tags"] = ""
        
        # Check for EEG data
        eeg_dir = session_dir / "Eeg"
        if eeg_dir.exists() and eeg_dir.is_dir():
            eeg_files = list(eeg_dir.glob("*.csv"))
            if eeg_files:
                session_data["eeg_file"] = str(eeg_files[0].resolve())
                try:
                    eeg_df = pd.read_csv(eeg_files[0])
                    session_data["eeg_samples"] = len(eeg_df)
                    session_data["eeg_channels"] = len(eeg_df.columns) - 1
                except Exception as e:
                    print(f"Error reading EEG file {eeg_files[0]}: {e}")
                    session_data["eeg_samples"] = 0
                    session_data["eeg_channels"] = 0
            else:
                session_data["eeg_file"] = None
                session_data["eeg_samples"] = 0
                session_data["eeg_channels"] = 0
        else:
            session_data["eeg_file"] = None
            session_data["eeg_samples"] = 0
            session_data["eeg_channels"] = 0
        
        # Check for ECG data
        ecg_dir = session_dir / "Ecg"
        if ecg_dir.exists() and ecg_dir.is_dir():
            ecg_files = list(ecg_dir.glob("*.csv"))
            session_data["ecg_file"] = str(ecg_files[0].resolve()) if ecg_files else None
        else:
            session_data["ecg_file"] = None
        
        # Check for Audio data
        audio_dir = session_dir / "Audio"
        if audio_dir.exists() and audio_dir.is_dir():
            audio_files = list(audio_dir.glob("*.wav"))
            session_data["audio_file"] = str(audio_files[0].resolve()) if audio_files else None
        else:
            session_data["audio_file"] = None
        
        # Check for Text data
        text_dir = session_dir / "Text"
        if text_dir.exists() and text_dir.is_dir():
            text_csv = text_dir / "text.csv"
            text_final = text_dir / "text_final.txt"
            session_data["text_csv_file"] = str(text_csv.resolve()) if text_csv.exists() else None
            session_data["text_final_file"] = str(text_final.resolve()) if text_final.exists() else None
        else:
            session_data["text_csv_file"] = None
            session_data["text_final_file"] = None
        
        # Check for Meteo data
        meteo_dir = session_dir / "Meteo"
        if meteo_dir.exists() and meteo_dir.is_dir():
            meteo_files = list(meteo_dir.glob("*.csv"))
            session_data["meteo_file"] = str(meteo_files[0].resolve()) if meteo_files else None
        else:
            session_data["meteo_file"] = None
        
        # Check for OSC data
        osc_dir = session_dir / "Osc"
        if osc_dir.exists() and osc_dir.is_dir():
            osc_csv = osc_dir / "osc.csv"
            osc_final = osc_dir / "text_final.txt"
            session_data["osc_csv_file"] = str(osc_csv.resolve()) if osc_csv.exists() else None
            session_data["osc_final_file"] = str(osc_final.resolve()) if osc_final.exists() else None
        else:
            session_data["osc_csv_file"] = None
            session_data["osc_final_file"] = None
        
        # Check for Drawing data
        drawing_dir = session_dir / "Drawing"
        if drawing_dir.exists() and drawing_dir.is_dir():
            drawing_files = list(drawing_dir.glob("*.png")) + list(drawing_dir.glob("*.jpg"))
            session_data["drawing_file"] = str(drawing_files[0].resolve()) if drawing_files else None
        else:
            session_data["drawing_file"] = None
        
        return session_data
    
    def create_dataset(self, sessions: List[Dict]) -> DatasetDict:
        """
        Create a Hugging Face dataset from session data, organized by user.
        
        Args:
            sessions: List of session dictionaries
            
        Returns:
            DatasetDict with splits per user
        """
        # Group sessions by user
        sessions_by_user = {}
        for session in sessions:
            user = session["user"]
            if user not in sessions_by_user:
                sessions_by_user[user] = []
            sessions_by_user[user].append(session)
        
        print(f"Creating dataset with {len(sessions_by_user)} users as separate splits")
        
        # Create a split for each user
        user_datasets = {}
        
        for user, user_sessions in sessions_by_user.items():
            dataset_dict = self._create_dataset_dict(user_sessions)
            user_datasets[user] = Dataset.from_dict(dataset_dict, features=self._get_features())
            print(f"  {user}: {len(user_sessions)} sessions")
        
        return DatasetDict(user_datasets)
    
    def _get_features(self) -> Features:
        """Define the schema for the dataset."""
        from datasets import Image
        
        return Features({
            "user": Value("string"),
            "session_id": Value("string"),
            "session_datetime": Value("string"),
            "tags": Value("string"),
            "eeg_samples": Value("int32"),
            "eeg_channels": Value("int32"),
            "eeg_file_path": Value("string"),  # Just path, not full data
            "ecg_file_path": Value("string"),  # Just path, not full data
            "text_file_path": Value("string"),
            "text_final": Value("string"),  # Keep small text
            "meteo_file_path": Value("string"),
            "osc_file_path": Value("string"),
            "osc_final": Value("string"),  # Keep small text
            "audio_file_path": Value("string"),  # Path only
            "drawing_file_path": Value("string"),  # Path only
        })
    
    def _create_dataset_dict(self, sessions: List[Dict]) -> Dict:
        """Create dataset dictionary from sessions."""
        dataset_dict = {
            "user": [],
            "session_id": [],
            "session_datetime": [],
            "tags": [],
            "eeg_samples": [],
            "eeg_channels": [],
            "eeg_file_path": [],
            "ecg_file_path": [],
            "audio_file_path": [],
            "text_file_path": [],
            "text_final": [],
            "meteo_file_path": [],
            "osc_file_path": [],
            "osc_final": [],
            "drawing_file_path": [],
        }
        
        for session in sessions:
            dataset_dict["user"].append(session["user"])
            dataset_dict["session_id"].append(session["session_id"])
            dataset_dict["session_datetime"].append(session["session_datetime"])
            dataset_dict["tags"].append(session.get("tags", ""))
            dataset_dict["eeg_samples"].append(session.get("eeg_samples", 0))
            dataset_dict["eeg_channels"].append(session.get("eeg_channels", 0))
            
            # Store file paths instead of full data
            dataset_dict["eeg_file_path"].append(session.get("eeg_file", ""))
            dataset_dict["ecg_file_path"].append(session.get("ecg_file", ""))
            dataset_dict["text_file_path"].append(session.get("text_csv_file", ""))
            dataset_dict["meteo_file_path"].append(session.get("meteo_file", ""))
            dataset_dict["osc_file_path"].append(session.get("osc_csv_file", ""))
            dataset_dict["audio_file_path"].append(session.get("audio_file", ""))
            dataset_dict["drawing_file_path"].append(session.get("drawing_file", ""))
            
            # Load only small text data
            if session.get("text_final_file"):
                try:
                    with open(session["text_final_file"], "r") as f:
                        dataset_dict["text_final"].append(f.read()[:1000])  # Limit to 1KB
                except Exception as e:
                    dataset_dict["text_final"].append("")
            else:
                dataset_dict["text_final"].append("")
            
            if session.get("osc_final_file"):
                try:
                    with open(session["osc_final_file"], "r") as f:
                        dataset_dict["osc_final"].append(f.read()[:1000])  # Limit to 1KB
                except Exception as e:
                    dataset_dict["osc_final"].append("")
            else:
                dataset_dict["osc_final"].append("")
        
        return dataset_dict
    
    def upload_dataset(
        self,
        dataset: DatasetDict,
        repo_id: Optional[str] = None,
        private: bool = False,
        commit_message: Optional[str] = None,
        uploaded_sessions: Optional[List[Dict]] = None,
    ):
        """
        Upload dataset to Hugging Face Hub with organized structure.
        
        The repository will be created automatically if it doesn't exist.
        Each user will have their own split in the dataset.
        
        Args:
            dataset: DatasetDict to upload (with user splits)
            repo_id: HF repo ID (overrides init value)
            private: Whether to make the dataset private
            commit_message: Custom commit message
            uploaded_sessions: List of sessions being uploaded (for cache update)
        """
        repo_id = repo_id or self.repo_id
        
        if not repo_id:
            raise ValueError("repo_id must be provided either in __init__ or upload_dataset")
        
        if not commit_message:
            commit_message = f"Upload Adalog sessions - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        total_sessions = sum(len(dataset[split]) for split in dataset.keys())
        print(f"Uploading dataset to {repo_id}...")
        print(f"Total: {total_sessions} sessions across {len(dataset)} users")
        
        # Get token and push to hub
        token = os.getenv("HF_TOKEN", "")
        dataset.push_to_hub(
            repo_id,
            private=private,
            token=token,
            commit_message=commit_message,
        )
        
        # Update cache after successful upload
        if self.use_cache and self.cache and uploaded_sessions:
            for session in uploaded_sessions:
                session_dir = Path(self.sessions_dir) / session['user'] / session['session_id']
                self.cache.mark_uploaded(session['user'], session['session_id'], session_dir)
            print(f"✓ Cache updated with {len(uploaded_sessions)} sessions")
        
        print(f"✓ Dataset uploaded successfully to https://huggingface.co/datasets/{repo_id}")
        print(f"✓ Access splits by user: dataset['Antoine'], dataset['Mar'], etc.")
        
        # Push to hub (creates repo if it doesn't exist)
    def create_and_upload(
        self,
        repo_id: Optional[str] = None,
        private: bool = False,
        force_reupload: bool = False,
    ):
        """
        Complete pipeline: scan, create, and upload dataset.
        
        Dataset will be organized with:
        - Each user as a separate split (e.g., dataset['Antoine'])
        - All modalities preserved per session
        - Metadata and tags included
        - Smart caching to avoid re-uploading unchanged sessions
        
        Args:
            repo_id: HF repo ID
            private: Whether to make the dataset private
            force_reupload: If True, ignore cache and upload all sessions
        """
    def create_and_upload(
        self,
        repo_id: Optional[str] = None,
        private: bool = False,
        force_reupload: bool = False,
        filter_users: Optional[list[str]] = None,
    ):
        """
        Complete pipeline: scan, create, and upload dataset incrementally.
        
        - Downloads existing dataset from HuggingFace
        - Adds only new/changed sessions
        - Prevents duplicates by matching session_id
        - Uploads merged dataset
        
        Args:
            repo_id: HF repo ID
            private: Whether to make the dataset private
            force_reupload: If True, ignore cache and upload all sessions
            filter_users: If provided, only upload sessions from these users
        """
        repo_id = repo_id or self.repo_id
        
        print("Scanning local sessions...")
        new_sessions = self.scan_sessions(skip_cached=not force_reupload)
        
        # Filter by users if specified
        if filter_users:
            new_sessions = [s for s in new_sessions if s['user'] in filter_users]
            print(f"Filtered to {len(new_sessions)} sessions from users: {', '.join(filter_users)}")
        
        # Try to download existing dataset from HuggingFace
        existing_dataset = None
        existing_count = 0
        if not force_reupload:
            try:
                print(f"Downloading existing dataset from {repo_id}...")
                from datasets import load_dataset
                
                token = os.getenv("HF_TOKEN", "")
                existing_dataset = load_dataset(repo_id, token=token)
                existing_count = sum(len(existing_dataset[split]) for split in existing_dataset.keys())
                print(f"✓ Found {existing_count} existing sessions online in splits: {list(existing_dataset.keys())}")
            except Exception as e:
                print(f"⚠️  Could not download existing dataset (will create new): {str(e)[:200]}")
                existing_dataset = None
        
        if not new_sessions and not force_reupload:
            print("✓ No new or changed sessions to upload.")
            if existing_count > 0:
                print(f"✓ Dataset already contains {existing_count} sessions")
            return
        
        # Create dataset from new sessions
        print(f"Processing {len(new_sessions)} new/changed sessions...")
        new_dataset = self.create_dataset(new_sessions)
        
        # Merge with existing dataset to avoid duplicates
        if existing_dataset is not None and not force_reupload:
            print("Merging with existing dataset (removing duplicates)...")
            final_dataset = self._merge_datasets(existing_dataset, new_dataset)
            total = sum(len(final_dataset[split]) for split in final_dataset.keys())
            print(f"✓ Final dataset: {total} sessions ({len(new_sessions)} new, {existing_count} existing)")
        else:
            final_dataset = new_dataset
            total = sum(len(final_dataset[split]) for split in final_dataset.keys())
            print(f"✓ Creating new dataset with {total} sessions")
        
        print("Uploading to HuggingFace...")
        self.upload_dataset(final_dataset, repo_id=repo_id, private=private, uploaded_sessions=new_sessions)
        
        print("\n✅ Upload complete!")
        print(f"📊 Dataset: https://huggingface.co/datasets/{repo_id}")
        print(f"📁 Structure: {len(final_dataset)} user splits")
        print(f"📈 Total sessions: {total}")
    
    def _merge_datasets(self, existing: DatasetDict, new: DatasetDict) -> DatasetDict:
        """
        Merge existing and new datasets, preventing duplicates.
        New sessions with same session_id will replace old ones.
        
        Args:
            existing: Dataset from HuggingFace
            new: New/changed sessions to add/update
            
        Returns:
            Merged DatasetDict with no duplicates
        """
        from datasets import concatenate_datasets
        
        merged = {}
        all_users = set(existing.keys()) | set(new.keys())
        
        for user in all_users:
            user_datasets = []
            
            if user in existing:
                existing_user = existing[user]
                
                # If there are new sessions for this user, filter out duplicates
                if user in new:
                    new_session_ids = set(new[user]['session_id'])
                    # Keep only sessions NOT being updated
                    filtered = existing_user.filter(
                        lambda x: x['session_id'] not in new_session_ids
                    )
                    if len(filtered) > 0:
                        user_datasets.append(filtered)
                else:
                    # No new sessions for this user, keep all existing
                    user_datasets.append(existing_user)
            
            # Add new/updated sessions
            if user in new:
                user_datasets.append(new[user])
            
            # Concatenate
            if len(user_datasets) == 1:
                merged[user] = user_datasets[0]
            elif len(user_datasets) > 1:
                merged[user] = concatenate_datasets(user_datasets)
        
        return DatasetDict(merged)


def main():
    """Main entry point for CLI usage."""
    import argparse
    
    # Get defaults from environment variables
    default_repo_id = os.getenv("HF_REPO_ID")
    default_token = os.getenv("HF_TOKEN")
    
    parser = argparse.ArgumentParser(
        description="Upload Adalog sessions to Hugging Face"
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        default=default_repo_id,
        help="Hugging Face repository ID (e.g., 'username/adalog-sessions'). Can be set via HF_REPO_ID env var.",
    )
    parser.add_argument(
        "--sessions-dir",
        type=str,
        default="sessions",
        help="Path to sessions directory (default: 'sessions')",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Make the dataset private",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Login to Hugging Face before uploading",
    )
    
    args = parser.parse_args()
    
    # Check if repo_id is provided
    if not args.repo_id:
        parser.error("--repo-id is required (or set HF_REPO_ID environment variable)")
    
    # Set token from environment if available
    if default_token and not args.login:
        os.environ["HF_TOKEN"] = default_token
        print("Using HF_TOKEN from environment")
    
    # Login if requested
    if args.login:
        print("Please login to Hugging Face:")
        login()
    
    # Create uploader and run pipeline
    uploader = AdalogDatasetUploader(
        sessions_dir=args.sessions_dir,
        repo_id=args.repo_id,
    )
    
    uploader.create_and_upload(
        repo_id=args.repo_id,
        private=args.private,
    )


if __name__ == "__main__":
    main()
