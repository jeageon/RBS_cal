from __future__ import annotations

from typing import Callable
from flask import Flask


def register_calculator_routes(
    app: Flask,
    run_estimate: Callable,
) -> None:
    app.add_url_rule(
        "/run",
        endpoint="run_estimate",
        view_func=run_estimate,
        methods=["POST"],
    )
