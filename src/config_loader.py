"""Configuration loader for expense tool."""

from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Resolve all paths relative to project root
    paths = cfg.get("paths", {})
    for key, val in paths.items():
        paths[key] = str((PROJECT_ROOT / val).resolve())

    # Ensure output directories exist
    for dir_key in ["output_dir", "exchange_rate_cache_dir"]:
        Path(paths[dir_key]).mkdir(parents=True, exist_ok=True)

    return cfg


def get_path(cfg: dict, key: str) -> Path:
    return Path(cfg["paths"][key])
