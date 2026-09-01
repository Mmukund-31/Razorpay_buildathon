"""Shared FastAPI dependencies: DB session, request id."""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def request_id_dep(request: Request) -> AsyncGenerator[str, None]:
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid
    yield rid


RequestId = Annotated[str, Depends(request_id_dep)]
