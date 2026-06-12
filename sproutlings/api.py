"""FastAPI shell — thin by design. All logic lives in service/repository
so the test suite exercises it without HTTP. Install: pip install fastapi uvicorn
Run: python run.py  ->  http://localhost:8000
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config, service
from .db import connect
from .repository import Repository

app = FastAPI(title="Sproutlings", version="1.0.0")
_conn = connect(config.DB_PATH)
repo = Repository(_conn)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


# --- request models ----------------------------------------------------------
class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    age: int = Field(ge=1, le=25)
    default_grade: str


class WorksheetIn(BaseModel):
    child_id: int
    field: str
    grade: str
    level: str


class TestIn(BaseModel):
    child_id: int
    fields: list[str]
    grade: str
    level: str
    total_questions: int = Field(default=20, ge=4, le=60)


class ScoreIn(BaseModel):
    # {"Mathematics": [7, 8], "Literature": [5, 6]}
    per_field: dict[str, tuple[int, int]]


class StatusIn(BaseModel):
    status: str


# --- meta ---------------------------------------------------------------
@app.get("/api/meta")
def meta():
    return {"grades": config.GRADES, "fields": config.FIELDS,
            "levels": config.LEVELS,
            "model": Path(config.LLM_MODEL_PATH).name}


# --- children ------------------------------------------------------------
@app.get("/api/children")
def children():
    return repo.list_children()


@app.post("/api/children", status_code=201)
def add_child(body: ChildIn):
    try:
        cid = repo.add_child(body.name, body.age, body.default_grade)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(409, f"Could not add child: {e}")
    return repo.get_child(cid)


@app.get("/api/children/{child_id}/stats")
def stats(child_id: int):
    if repo.get_child(child_id) is None:
        raise HTTPException(404, "Child not found")
    return repo.child_stats(child_id)


@app.get("/api/children/{child_id}/packets")
def packets(child_id: int):
    return repo.list_packets(child_id)


# --- generation -----------------------------------------------------------
@app.post("/api/worksheets", status_code=201)
def make_worksheet(body: WorksheetIn):
    try:
        return service.generate_worksheet_packet(
            repo, body.child_id, body.field, body.grade, body.level)
    except service.GenerationError as e:
        raise HTTPException(422, str(e))
    except Exception as e:                       # LLM unreachable etc.
        raise HTTPException(502, str(e))


@app.post("/api/tests", status_code=201)
def make_test(body: TestIn):
    try:
        return service.generate_test_packet(
            repo, body.child_id, body.fields, body.grade, body.level,
            body.total_questions)
    except service.GenerationError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, str(e))


# --- packet lifecycle ---------------------------------------------------
@app.get("/api/packets/{packet_id}")
def get_packet(packet_id: int):
    p = repo.get_packet(packet_id)
    if p is None:
        raise HTTPException(404, "Packet not found")
    return p


@app.patch("/api/packets/{packet_id}/status")
def set_status(packet_id: int, body: StatusIn):
    if repo.get_packet(packet_id) is None:
        raise HTTPException(404, "Packet not found")
    try:
        repo.set_packet_status(packet_id, body.status)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return repo.get_packet(packet_id)


@app.post("/api/packets/{packet_id}/score")
def score_test(packet_id: int, body: ScoreIn):
    try:
        return service.record_test_result(repo, packet_id, body.per_field)
    except (service.GenerationError, ValueError) as e:
        raise HTTPException(422, str(e))


# --- frontend -----------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")

app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
