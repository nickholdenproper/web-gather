"""FastAPI REST API for programmatic crawling - mirrors yt-transcriber style.

Endpoints:
  POST /v1/jobs          start a crawl  {"sources": [...], "options": {...}}
  GET  /v1/jobs          list job ids
  GET  /v1/jobs/{id}     job status / result summary
  GET  /v1/jobs/{id}/files/{name}   download a corpus file
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import __version__
from .pipeline import PipelineOptions, PipelineResult, crawl


class CrawlOptionsModel(BaseModel):
    max_pages: int = Field(50, ge=1, le=10000)
    max_depth: int = Field(3, ge=0, le=10)
    same_domain: bool = True
    delay: float = Field(1.0, ge=0.0, le=60.0)
    concurrency: int = Field(4, ge=1, le=64)
    timeout: float = Field(20.0, ge=1.0)
    retries: int = Field(2, ge=0, le=5)
    ignore_robots: bool = False
    follow_feed_sitemap: bool = True


class CrawlRequest(BaseModel):
    sources: list[str] = Field(min_length=1)
    options: Optional[CrawlOptionsModel] = None


class _Job:
    def __init__(self, job_id: str, out_dir: Path):
        self.job_id = job_id
        self.out_dir = out_dir
        self.thread: Optional[threading.Thread] = None
        self.result: Optional[PipelineResult] = None
        self.error: Optional[str] = None
        self.finished = threading.Event()


class JobStore:
    def __init__(self):
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def add(self, job: _Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Optional[_Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._jobs.keys())


store = JobStore()
_executor = ThreadPoolExecutor(max_workers=8)


def _run_job(job: _Job, request: CrawlRequest) -> None:
    try:
        opts = request.options or CrawlOptionsModel()
        pipeline_opts = PipelineOptions(
            max_pages=opts.max_pages,
            max_depth=opts.max_depth,
            same_domain=opts.same_domain,
            delay=opts.delay,
            concurrency=opts.concurrency,
            timeout=opts.timeout,
            retries=opts.retries,
            ignore_robots=opts.ignore_robots,
            follow_feed_sitemap=opts.follow_feed_sitemap,
            out_dir=job.out_dir,
        )
        job.result = crawl(request.sources, pipeline_opts)
    except Exception as exc:  # noqa: BLE001
        job.error = str(exc)
    finally:
        job.finished.set()


def create_app(data_root: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title="Web Gather API", version=__version__)
    root = data_root or Path.cwd() / "api_jobs"

    @app.get("/")
    def index() -> dict:
        return {
            "service": "web-gather",
            "version": __version__,
            "docs": "/docs",
            "jobs": "/v1/jobs",
        }

    @app.post("/v1/jobs")
    def start_job(request: CrawlRequest) -> dict:
        job_id = uuid.uuid4().hex[:12]
        out_dir = root / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        job = _Job(job_id, out_dir)
        store.add(job)
        job.thread = _executor.submit(_run_job, job, request)
        return {"job_id": job_id}

    @app.get("/v1/jobs")
    def list_jobs() -> dict:
        return {"jobs": store.ids()}

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        state = "done" if job.finished.is_set() else "running"
        body: dict = {"job_id": job_id, "state": state}
        if job.error:
            body["error"] = job.error
        if job.result is not None:
            body["status"] = job.result.status.to_dict()
            body["articles"] = len(job.result.articles)
            body["written"] = [str(w) for w in job.result.written]
        return body

    @app.get("/v1/jobs/{job_id}/files/{file_name}")
    def job_file(job_id: str, file_name: str) -> FileResponse:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        path = Path(job.out_dir) / file_name
        if not path.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(path)

    return app


app = create_app()