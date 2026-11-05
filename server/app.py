"""HTTP API for resumable, hash-verified uploads.

POST /uploads                         create a session  {filename, size, sha256}
PUT  /uploads/{id}/chunks?offset=N    upload bytes; header X-Chunk-SHA256
GET  /uploads/{id}                    status (state, received_bytes, ...)
POST /uploads/{id}/finalize           verify full-file SHA-256 -> COMPLETE or REJECTED
GET  /uploads, /uploads/{id}/events   used by the live status page
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config, db, uploads

@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="Reliable video upload", lifespan=lifespan)
STATIC = Path(__file__).parent / "static"


@app.exception_handler(uploads.UploadError)
def _upload_error(_request, exc: uploads.UploadError):
    return JSONResponse(status_code=exc.status,
                        content={"error": exc.code, "message": exc.message, **exc.extra})


class CreateUpload(BaseModel):
    filename: str
    size: int
    sha256: str


@app.post("/uploads", status_code=201)
def create_upload(body: CreateUpload):
    return uploads.create(body.filename, body.size, body.sha256)


@app.get("/uploads")
def list_uploads():
    return uploads.list_all()


@app.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    return uploads.get(upload_id)


@app.get("/uploads/{upload_id}/events")
def get_events(upload_id: str):
    return uploads.events(upload_id)


@app.put("/uploads/{upload_id}/chunks")
async def put_chunk(upload_id: str, request: Request, offset: int = Query(...),
                    x_chunk_sha256: str = Header(...)):
    # Read at most MAX_CHUNK_BYTES + 1 so an oversized body is rejected without buffering it all.
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > config.MAX_CHUNK_BYTES:
            break
    info, duplicate = await run_in_threadpool(
        uploads.put_chunk, upload_id, offset, bytes(data), x_chunk_sha256)
    return {**info, "duplicate": duplicate}


@app.post("/uploads/{upload_id}/finalize")
def finalize(upload_id: str):
    return uploads.finalize(upload_id)


@app.get("/")
def status_page():
    return FileResponse(STATIC / "status.html")


@app.get("/health")
def health():
    return {"ok": True}
