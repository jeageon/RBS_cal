from __future__ import annotations

from typing import Callable
from flask import Flask


def register_common_routes(
    app: Flask,
    index: Callable,
    health: Callable,
) -> None:
    app.add_url_rule("/", endpoint="index", view_func=index, methods=["GET"])
    app.add_url_rule("/health", endpoint="health", view_func=health, methods=["GET"])
