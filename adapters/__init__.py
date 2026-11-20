"""Adapter registry. Each module in this folder exposes `ADAPTER = <Adapter subclass>`."""
import importlib

ALL_SITES = [
    "playstation", "amazon", "fnac", "darty", "boulanger", "micromania",
    "cultura", "cdiscount", "carrefour", "leclerc", "auchan",
]


def load(name: str, cfg: dict):
    mod = importlib.import_module(f"adapters.{name}")
    return mod.ADAPTER(cfg)
