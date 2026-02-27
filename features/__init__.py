from __future__ import annotations

from .calculator_routes import register_calculator_routes
from .common_routes import register_common_routes
from .designer_routes import register_designer_routes

__all__ = ["register_common_routes", "register_calculator_routes", "register_designer_routes"]
