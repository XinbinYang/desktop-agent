"""Plugin system MVP — discover and load plugins from ~/.desktop-agent/plugins/."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


PLUGINS_DIR = Path.home() / ".desktop-agent" / "plugins"


class Plugin:
    """Base class for Desktop Agent plugins."""

    name: str = ""
    version: str = "0.1.0"
    description: str = ""

    def on_load(self) -> None:
        """Called when the plugin is loaded."""

    def on_unload(self) -> None:
        """Called when the plugin is unloaded."""

    def get_tools(self) -> List[Any]:
        """Return a list of BaseTool instances this plugin provides."""
        return []

    def get_routes(self) -> List[Any]:
        """Return a list of FastAPI APIRouter instances this plugin provides."""
        return []


class PluginManager:
    """Manages plugin lifecycle: discovery, loading, and unloading."""

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._loaded = False

    @property
    def plugins(self) -> Dict[str, Plugin]:
        return self._plugins

    def discover_and_load(self) -> int:
        """Scan plugins directory and load all valid plugins."""
        if self._loaded:
            return len(self._plugins)

        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        loaded = 0

        for entry in sorted(PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            plugin_file = entry / "plugin.py"
            if not plugin_file.exists():
                plugin_file = entry / "__init__.py"
            if not plugin_file.exists():
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"desktop_agent_plugin_{entry.name}", str(plugin_file)
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)

                # Look for a Plugin subclass or register function
                plugin: Optional[Plugin] = None
                if hasattr(module, "register"):
                    plugin = module.register()
                else:
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
                            plugin = attr()
                            break

                if plugin is None:
                    continue

                plugin.name = entry.name
                plugin.on_load()
                self._plugins[entry.name] = plugin
                loaded += 1
                print(f"[Plugin] Loaded: {entry.name}")
            except Exception as e:
                print(f"[Plugin] Failed to load {entry.name}: {e}")

        self._loaded = True
        return loaded

    def unload_all(self) -> None:
        for name, plugin in self._plugins.items():
            try:
                plugin.on_unload()
            except Exception:
                pass
        self._plugins.clear()
        self._loaded = False

    def get_all_tools(self) -> List[Any]:
        tools: List[Any] = []
        for plugin in self._plugins.values():
            tools.extend(plugin.get_tools())
        return tools


_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
