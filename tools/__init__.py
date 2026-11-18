# tools/__init__.py
"""Araç paketi. discover_tools() her araç dosyasını import eder,
dekoratörler registry'yi doldurur."""
import importlib
import pkgutil

from ._registry import TOOLS, register_tool, get_config

_discovered = False


def discover_tools():
    """tools/ altındaki tüm .py dosyalarını import eder (bir kez)."""
    global _discovered
    if _discovered:
        return list(TOOLS.keys())

    package = __name__  # "tools"
    for _, mod_name, _ in pkgutil.iter_modules(__path__):
        # _registry, _birsey gibi özel modülleri atla
        if mod_name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{package}.{mod_name}")
        except Exception as e:
            print(f"[tools] {mod_name} yüklenemedi: {e}")

    _discovered = True
    print(f"[tools] Yüklendi: {', '.join(sorted(TOOLS.keys())) or '(yok)'}")
    return list(TOOLS.keys())


__all__ = ["TOOLS", "register_tool", "get_config", "discover_tools"]