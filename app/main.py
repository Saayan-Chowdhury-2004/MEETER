"""Entry point: python -m app.main

Starts the local FastAPI control API and the observation loop.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

import uvicorn

from app.agent import Agent
from app.api import init as api_init
from app.config import load_config
from app.logging_config import setup_logging
from app.storage.repository import Repository
from app.storage.sqlite import Database

log = logging.getLogger("meeting-agent")


def build_agent(config_path: str = "config/default.yaml") -> tuple:
    cfg = load_config(config_path)
    Path(cfg.agent.data_dir).mkdir(parents=True, exist_ok=True)
    setup_logging(cfg.logging.level, cfg.logging.file)
    db = Database(os.path.join(cfg.agent.data_dir, "events.db"))
    repo = Repository(db)
    agent = Agent(cfg, repo)
    return agent, repo, cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="Local third-person meeting agent")
    parser.add_argument("--config", default=os.environ.get("MEETING_AGENT_CONFIG", "config/default.yaml"))
    parser.add_argument("--mode", default=None, help="observe|suggest|assist|autonomous (overrides config)")
    parser.add_argument("--no-api", action="store_true", help="run loop without the HTTP API")
    parser.add_argument("--dry-run", action="store_true", help="force automation dry-run")
    args = parser.parse_args()

    agent, repo, cfg = build_agent(args.config)
    if args.mode:
        agent.set_mode(args.mode)
    if args.dry_run:
        cfg.automation.dry_run = True

    agent.start_capture()
    agent.start_killswitch()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run() -> None:
        api_init(agent, repo)
        agent_task = asyncio.create_task(agent.run())
        server_config = uvicorn.Config(
            app=_import_fastapi_app(),
            host=cfg.api.host,
            port=cfg.api.port,
            log_level="info",
        )
        server = uvicorn.Server(server_config)
        server_task = asyncio.create_task(server.serve())
        log.info("API ready at http://%s:%d (dashboard at /)", cfg.api.host, cfg.api.port)
        await asyncio.gather(agent_task, server_task)

    try:
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        log.info("shutting down (user interrupt)")
        agent.stop()
    finally:
        loop.close()


def _import_fastapi_app():
    from app.api import app

    return app


if __name__ == "__main__":
    main()
