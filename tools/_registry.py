# tools/_registry.py
"""Araç kayıt sistemi. Circular import'u önlemek için bağımsız tutulur."""
import json
import os

TOOLS = {}                 # name -> {name, description, parameters, fn}
_config_cache = None


def register_tool(name, description, parameters):
    """Bir fonksiyonu araç olarak kaydeder.
    Kullanım: @register_tool("ad", "açıklama", {"param": "string - açıklama"})
    """
    def decorator(fn):
        TOOLS[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "fn": fn,
        }
        return fn
    return decorator


def get_config():
    """config.json'u bir kez okur, cache'ler."""
    global _config_cache
    if _config_cache is None:
        path = os.environ.get("JARVIS_CONFIG", "config.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _config_cache = json.load(f)
        else:
            _config_cache = {}
    return _config_cache