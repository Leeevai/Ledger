from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import errors
#from .authz import load_permission_cache
from .db import pool
from .routers import sessions, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    with pool.connection() as conn:
        # load_permission_cache(conn)
        pass
    yield
    pool.close()


app = FastAPI(title="Ledger API", version="1.0.0", lifespan=lifespan)
errors.install(app)

for r in (users.router, sessions.router):
    app.include_router(r)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}
