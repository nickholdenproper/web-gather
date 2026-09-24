"""FastAPI - the "usable from any website" layer.

Endpoints:
  GET  /                     browser GUI (web-gather studio)
  POST /v1/jobs              start a crawl      {"sources": [...], "options": {...}}
  GET  /v1/jobs              list job ids
  GET  /v1/jobs/{id}         job status / summary
  GET  /v1/jobs/{id}/files/{name}          download a corpus file
  GET  /v1/search?q=&engine=&limit=       free web search (synchronous)
  POST /v1/search-and-crawl               search -> crawl -> corpus job
  GET  /v1/tools                           machine-readable AI tool list
  POST /v1/research         start a research job   {"goal": "...", "options": {...}}
  GET  /v1/research/{id}    research result / findings
  GET  /v1/research/{id}/files/{name}     download findings.json / report.md

CORS is open by default so any website may call; lock down with
``--cors-origin https://...`` (repeatable) or create_app(cors_origins=[...]).
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from . import __version__
from .answer import AskOptions, ask
from .llm import resolve_client
from .pipeline import PipelineOptions, PipelineResult, crawl
from .research import ResearchOptions, ResearchResult, research
from .search import BROWSER_ENGINES, search_web
from .tools import TOOLS


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
    browser_mode: str = Field("auto", pattern="^(auto|always|never)$")
    blocked: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    engine: str = "auto"
    limit: int = Field(8, ge=1, le=50)
    crawl: bool = False


class SearchAndCrawlRequest(BaseModel):
    query: str = Field(min_length=1)
    engine: str = "auto"
    limit: int = Field(5, ge=1, le=20)
    options: Optional[CrawlOptionsModel] = None
    min_score: int = Field(25, ge=0, le=100)


class ResearchOptionsModel(BaseModel):
    engine: str = "auto"
    max_queries: int = Field(4, ge=1, le=10)
    max_sites: int = Field(6, ge=1, le=30)
    min_score: int = Field(30, ge=0, le=100)
    max_findings_per_site: int = Field(3, ge=1, le=10)
    browser_mode: str = Field("auto", pattern="^(auto|always|never)$")
    use_llm: bool = False
    blocked: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)


class ResearchRequest(BaseModel):
    goal: str = Field(min_length=1)
    options: Optional[ResearchOptionsModel] = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    engine: str = "auto"
    max_sites: int = Field(6, ge=1, le=15)
    browser_mode: str = Field("auto", pattern="^(auto|always|never)$")
    use_llm: bool = True


class _Job:
    def __init__(self, job_id: str, out_dir: Path, kind: str):
        self.job_id = job_id
        self.out_dir = out_dir
        self.kind = kind
        self.result: object = None
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


crawl_store = JobStore()
research_store = JobStore()
_executor = ThreadPoolExecutor(max_workers=8)


def _job_response(job: _Job) -> dict:
    state = "done" if job.finished.is_set() else "running"
    body: dict = {"job_id": job.job_id, "kind": job.kind, "state": state}
    if job.error:
        body["error"] = job.error
    if job.result is not None:
        if isinstance(job.result, PipelineResult):
            body["status"] = job.result.status.to_dict()
            body["articles"] = len(job.result.articles)
            body["written"] = [str(w) for w in job.result.written]
        elif isinstance(job.result, ResearchResult):
            body.update(job.result.to_dict())
        else:
            body["result"] = job.result
    return body


def _new_job(store: JobStore, root: Path, kind: str) -> _Job:
    job_id = uuid.uuid4().hex[:12]
    out_dir = root / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    job = _Job(job_id, out_dir, kind)
    store.add(job)
    return job


def _to_pipeline_opts(opts: CrawlOptionsModel, out_dir: Path) -> PipelineOptions:
    return PipelineOptions(
        max_pages=opts.max_pages,
        max_depth=opts.max_depth,
        same_domain=opts.same_domain,
        delay=opts.delay,
        concurrency=opts.concurrency,
        timeout=opts.timeout,
        retries=opts.retries,
        ignore_robots=opts.ignore_robots,
        follow_feed_sitemap=opts.follow_feed_sitemap,
        browser_mode=opts.browser_mode,
        blocked=opts.blocked or None,
        allowed=opts.allowed or None,
        out_dir=out_dir,
    )


def create_app(
    data_root: Optional[Path] = None,
    reseach_root: Optional[Path] = None,
    cors_origins: Optional[list[str]] = None,
    static_dir: Optional[Path] = None,
) -> FastAPI:
    app = FastAPI(title="Web Gather API", version=__version__)
    root = data_root or Path.cwd() / "api_jobs"
    r_root = reseach_root or Path.cwd() / "research_jobs"
    origins = cors_origins if cors_origins is not None else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # GUI (web-gather studio)
    gui_dir = static_dir or _static_dir()
    if gui_dir.exists():
        app.mount("/static", StaticFiles(directory=gui_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(gui_dir / "index.html")

    @app.get("/api-info")
    def api_info() -> dict:
        return {
            "service": "web-gather",
            "version": __version__,
            "docs": "/docs",
            "gui": "/",
            "cors_open": origins == ["*"],
        }

    # ---------------- crawl jobs ----------------

    @app.post("/v1/jobs")
    def start_job(request: CrawlJobRequest) -> dict:
        job = _new_job(crawl_store, root, "crawl")
        job.thread = _executor.submit(
            _run_crawl, job, request.sources, request.options
        )
        return {"job_id": job.job_id}

    @app.post("/v1/search-and-crawl")
    def search_and_crawl(request: SearchAndCrawlRequest) -> dict:
        job = _new_job(crawl_store, root, "search-and-crawl")
        job.thread = _executor.submit(_run_search_and_crawl, job, request)
        return {"job_id": job.job_id}

    @app.get("/v1/jobs")
    def list_jobs() -> dict:
        return {"jobs": crawl_store.ids()}

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = crawl_store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return _job_response(job)

    @app.get("/v1/jobs/{job_id}/files/{file_name}")
    def job_file(job_id: str, file_name: str) -> FileResponse:
        job = crawl_store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        path = Path(job.out_dir) / file_name
        if not path.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(path)

    # ---------------- free search ----------------

    @app.get("/v1/search")
    def search(
        q: str = Query(..., min_length=1),
        engine: str = "auto",
        limit: int = Query(8, ge=1, le=50),
        block: str = Query("", description="comma-separated blocked domains"),
    ) -> dict:
        from .blocks import BlockList

        blocklist = BlockList(blocked=[b for b in block.split(",") if b])
        try:
            results = search_web(q, engine=engine, limit=limit, blocklist=blocklist)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))
        return {"query": q, "engine": engine, "results": [r.to_dict() for r in results]}

    # ---------------- AI tools ----------------

    @app.get("/v1/tools")
    def tools() -> dict:
        return {"tools": TOOLS}

    # ---------------- ask: one paragraph answer ----------------

    @app.post("/v1/ask")
    def ask_question(request: AskRequest) -> dict:
        from .answer import client_if_available

        opts = AskOptions(
            engine=request.engine,
            max_sites=request.max_sites,
            browser_mode=request.browser_mode,
            use_llm=request.use_llm,
        )
        model = client_if_available(request.use_llm)
        result = ask(request.question, opts, llm=model)
        return result.to_dict()

    # ---------------- research jobs ----------------

    @app.post("/v1/research")
    def start_research(request: ResearchRequest) -> dict:
        job = _new_job(research_store, r_root, "research")
        job.thread = _executor.submit(_run_research, job, request)
        return {"job_id": job.job_id}

    @app.get("/v1/research")
    def list_research() -> dict:
        return {"jobs": research_store.ids()}

    @app.get("/v1/research/{job_id}")
    def research_status(job_id: str) -> dict:
        job = research_store.get(job_id)
        if job is None:
            raise HTTPException(404, "research job not found")
        return _job_response(job)

    @app.get("/v1/research/{job_id}/files/{file_name}")
    def research_file(job_id: str, file_name: str) -> FileResponse:
        job = research_store.get(job_id)
        if job is None:
            raise HTTPException(404, "research job not found")
        path = Path(job.out_dir) / file_name
        if not path.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(path)

    return app


def _static_dir() -> Path:
    try:
        from importlib.resources import files

        return Path(files("web_gather.static").joinpath("index.html").parents[0])
    except Exception:  # noqa: BLE001
        return Path(__file__).parent / "static"


class CrawlJobRequest(BaseModel):
    sources: list[str] = Field(min_length=1)
    options: Optional[CrawlOptionsModel] = None


def _run_crawl(job: _Job, sources: list[str], opts: Optional[CrawlOptionsModel]) -> None:
    try:
        opts = opts or CrawlOptionsModel()
        job.result = crawl(sources, _to_pipeline_opts(opts, job.out_dir))
    except Exception as exc:  # noqa: BLE001
        job.error = str(exc)
    finally:
        job.finished.set()


def _run_search_and_crawl(job: _Job, request: SearchAndCrawlRequest) -> None:
    try:
        from .blocks import BlockList
        from .select import select_sites

        opts = request.options or CrawlOptionsModel()
        block = BlockList(blocked=opts.blocked or [])
        blocklist = block if (block.blocked or block.allowed) else None
        results = search_web(request.query, engine=request.engine, limit=request.limit, blocklist=block)
        selected = select_sites(results, request.query, min_score=request.min_score)[: request.limit]
        sources = [s.url for s in selected]
        jobs_options = CrawlOptionsModel(
            max_pages=opts.max_pages,
            max_depth=max(0, min(1, opts.max_depth)),
            same_domain=False,
            delay=opts.delay,
            concurrency=opts.concurrency,
            timeout=opts.timeout,
            retries=opts.retries,
            ignore_robots=opts.ignore_robots,
            follow_feed_sitemap=False,
            browser_mode=opts.browser_mode,
            blocked=opts.blocked,
        )
        job.result = crawl(sources, _to_pipeline_opts(jobs_options, job.out_dir))
    except Exception as exc:  # noqa: BLE001
        job.error = str(exc)
    finally:
        job.finished.set()


def _run_research(job: _Job, request: ResearchRequest) -> None:
    try:
        o = request.options or ResearchOptionsModel()
        llm = resolve_client() if o.use_llm else None
        opts = ResearchOptions(
            goal=request.goal,
            engine=o.engine,
            max_queries=o.max_queries,
            max_sites=o.max_sites,
            min_score=o.min_score,
            max_findings_per_site=o.max_findings_per_site,
            browser_mode=o.browser_mode,
            use_llm=o.use_llm,
            blocked=o.blocked or None,
            allowed=o.allowed or None,
            out_dir=job.out_dir,
        )
        job.result = research(request.goal, opts, llm=llm)
    except Exception as exc:  # noqa: BLE001
        job.error = str(exc)
    finally:
        job.finished.set()


app = create_app()