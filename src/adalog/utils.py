from pathlib import Path

def get_asset_path(asset_name: str) -> Path:
    """Returns the absolute path to an asset in the adalog/assets directory."""
    return Path(__file__).resolve().parent / "assets" / asset_name
