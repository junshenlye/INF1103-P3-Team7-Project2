"""Application managers that coordinate domain rules and adapters."""

from .ai_manager import AIManager
from .data_manager import DataManager
from .logic_manager import LogicManager
from .io_manager import IOManager

__all__ = ["AIManager", "DataManager", "IOManager", "LogicManager"]
