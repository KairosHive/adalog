import sounddevice as sd
import soundfile as sf
from pathlib import Path

def get_asset_path(asset_name: str) -> Path:
    """Returns the absolute path to an asset in the adalog/assets directory."""
    return Path(__file__).resolve().parent / "assets" / asset_name

def play_audio_file(file_path: Path):
    """Plays an audio file using sounddevice and soundfile."""
    try:
        data, fs = sf.read(file_path, dtype='float32')
        sd.play(data, fs)
        sd.wait()  # Wait until file is done playing
    except Exception as e:
        print(f"Error playing audio file {file_path}: {e}")
