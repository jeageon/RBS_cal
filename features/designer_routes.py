from __future__ import annotations

from typing import Callable
from flask import Flask


def register_designer_routes(
    app: Flask,
    run_design: Callable,
    get_task: Callable,
) -> None:
    app.add_url_rule(
        "/design",
        endpoint="run_design",
        view_func=run_design,
        methods=["POST"],
    )
    app.add_url_rule(
        "/tasks/<task_id>",
        endpoint="get_task",
        view_func=get_task,
        methods=["GET"],
    )
