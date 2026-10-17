"""Version checks remain separate from school accounts and task scheduling."""
import asyncio

from fastapi import Query

from core.updates import UpdateChecker


def install(app):
    app.state.update_checker = UpdateChecker()

    @app.get("/api/system/updates")
    async def check_updates(manual: bool = Query(False)):
        return await asyncio.to_thread(app.state.update_checker.check, manual=manual)
