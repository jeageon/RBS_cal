from __future__ import annotations

from .calculator_routes import register_calculator_routes
from .common_routes import register_common_routes
from .designer_routes import register_designer_routes
from .plasmid_designer_integration import register_plasmid_designer

__all__ = [
    "register_common_routes",
    "register_calculator_routes",
    "register_designer_routes",
    "register_plasmid_designer",
]
