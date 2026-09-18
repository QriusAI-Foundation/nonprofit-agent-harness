"""Entrypoint for `uvicorn nonprofit_harness.main:app`, and for the container image.

Agents are discovered from HARNESS_AGENTS, a comma-separated list of import paths:

    HARNESS_AGENTS=examples.summarizer:SummarizerAgent
"""

from __future__ import annotations

import importlib
import logging
import os
import sys

from nonprofit_harness.api.app import create_app
from nonprofit_harness.core.registry import registry

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("nonprofit_harness")


def load_agents_from_env() -> None:
    # Agents live in the deploying project, not in this package.
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    for path in (p.strip() for p in os.getenv("HARNESS_AGENTS", "").split(",") if p.strip()):
        module_name, _, attribute = path.partition(":")
        if not attribute:
            logger.warning("Skipping %r: expected module:ClassName", path)
            continue
        try:
            module = importlib.import_module(module_name)
            agent_class = getattr(module, attribute)
        except (ImportError, AttributeError) as exc:
            logger.error("Could not load agent %r: %s", path, exc)
            continue
        if agent_class.name not in registry:
            registry.register(agent_class())
            logger.info("Registered agent %s", agent_class.name)


load_agents_from_env()
app = create_app()
