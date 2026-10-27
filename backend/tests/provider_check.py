"""Build every agent in a fresh process and print how its model is wired.

Run as ``python -m tests.provider_check`` from ``backend/``. The key is removed from
``os.environ`` after Settings has loaded, so the output shows whether each agent takes
the key from Settings (the run-without-Docker path) or from the process environment.
"""

from __future__ import annotations

import json
import os


def main() -> int:
    from app.agents.deep_analysis_agent import get_deep_analysis_agent
    from app.agents.relevance_screener_agent import get_second_pass_agent
    from app.config import settings  # noqa: F401  (loads Settings before the key is removed)
    from tests.test_agent_model_settings import _agent_factories

    factories = [(name, factory) for name, factory, _ in _agent_factories()]
    factories.append(("deep_analysis", get_deep_analysis_agent))
    factories.append(("second_pass_v2", lambda: get_second_pass_agent(prompt_version="v2")))

    os.environ.pop("DEEPSEEK_API_KEY", None)

    rows = []
    for name, factory in factories:
        row = {
            "agent": name,
            "model_class": None,
            "base_url": None,
            "api_key": None,
            "model_name": None,
            "error": None,
        }
        try:
            agent = factory()
            model = agent.model
            row["model_class"] = type(model).__name__
            row["model_name"] = getattr(model, "model_name", None)
            client = getattr(model, "client", None)
            if client is not None:
                row["base_url"] = str(client.base_url).rstrip("/")
                row["api_key"] = client.api_key
        except Exception as exc:
            row["error"] = repr(exc)
        rows.append(row)
    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
