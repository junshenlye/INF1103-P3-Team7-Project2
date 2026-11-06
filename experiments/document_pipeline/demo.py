"""Local opt-in ingestion demo. Never imported by the production application."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import uuid

from flask import Flask, jsonify, request, send_from_directory
from PIL import Image
import httpx
from openai import APIError, APITimeoutError
from src.ai_manager.qwen_client import create_client
from .document import convert
from .inference import MeteredProvider, proposed
from .review import render


def create_demo(root, docling_url="http://127.0.0.1:15001", processor=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    jobs = {}
    for folder in root.iterdir():
        if (
            not folder.is_dir()
            or len(folder.name) != 32
            or any(c not in "0123456789abcdef" for c in folder.name)
        ):
            continue
        snapshot = folder / "job.json"
        if not snapshot.exists():
            continue
        try:
            data = json.loads(snapshot.read_text())
            if data["stage"] == "ready":
                data["result"] = json.loads((folder / "result.json").read_text())
            elif data["stage"] != "error":
                data.update(
                    stage="error",
                    message="Processing was interrupted. Please submit this module again.",
                )
            jobs[folder.name] = data
        except (ValueError, KeyError, OSError):
            continue
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(2)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-demo")
    app.extensions["document_demo"] = {"jobs": jobs, "executor": executor}

    def update(job_id, **values):
        with lock:
            jobs[job_id].update(values)
            folder = root / job_id
            if "result" in values:
                (folder / "result.json").write_text(
                    json.dumps(values["result"], indent=2)
                )
            snapshot = {k: v for k, v in jobs[job_id].items() if k != "result"}
            temporary = folder / "job.json.tmp"
            temporary.write_text(json.dumps(snapshot, indent=2))
            temporary.replace(folder / "job.json")

    async def process(job_id, paths, title, credit, folder):
        docs = []
        for index, path in enumerate(paths):
            update(
                job_id,
                stage="reading",
                message=f"Reading document {index + 1} of {len(paths)}…",
            )
            doc, _ = await convert(
                path, folder / f"source-{index}", docling_url, render_pages=True
            )
            docs.append(doc)
        document = (
            docs[0]
            if len(docs) == 1
            else {
                "document_sha256": hashlib.sha256(
                    "".join(d["document_sha256"] for d in docs).encode()
                ).hexdigest(),
                "elements": [e for d in docs for e in d["elements"]],
                "documents": [
                    {k: v for k, v in d.items() if k != "elements"} for d in docs
                ],
            }
        )
        update(
            job_id,
            stage="interpreting",
            message="Finding assessments and checking their source references…",
        )
        async with create_client().with_options(timeout=300, max_retries=0) as client:
            result = await proposed(MeteredProvider(client), document, title, credit)
        (folder / "result.json").write_text(json.dumps(result, indent=2))
        render(folder)
        return result

    def worker(job_id, paths, title, credit, folder):
        try:
            result = asyncio.run(
                (processor or process)(job_id, paths, title, credit, folder)
            )
            update(
                job_id,
                stage="ready",
                message="Your assessments are ready.",
                result=result,
            )
        except Exception as error:
            # Keep credential-bearing provider diagnostics out of responses/logs.
            code = "unverified_document"
            message = "We couldn’t verify these assessment details. Try a clearer file or a smaller set of pages."
            if isinstance(
                error, (httpx.TimeoutException, APITimeoutError, asyncio.TimeoutError)
            ):
                code, message = (
                    "timeout",
                    "This took too long. Try fewer pages, or try again in a moment.",
                )
            elif isinstance(error, httpx.HTTPError):
                code, message = (
                    "document_service",
                    "The document service is unavailable. Please try again in a moment.",
                )
            elif isinstance(error, APIError):
                code, message = (
                    "ai_service",
                    "The AI service could not respond. Please try again in a moment.",
                )
            app.logger.warning("Document job failed: %s", type(error).__name__)
            update(job_id, stage="error", error_code=code, message=message)
        finally:
            slots.release()

    @app.before_request
    def same_origin():
        origin = request.headers.get("Origin")
        if (
            request.method == "POST"
            and origin
            and origin.rstrip("/") != request.host_url.rstrip("/")
        ):
            return jsonify(error="Open StackPlan directly to upload documents."), 403

    @app.get("/jobs")
    def list_jobs():
        with lock:
            return jsonify(
                [
                    {"id": job_id, "module": data["module"], "stage": data["stage"]}
                    for job_id, data in jobs.items()
                ]
            )

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/")
    def index():
        return Path(__file__).with_name("demo.html").read_text()

    @app.post("/jobs")
    def submit():
        title = request.form.get("module", "").strip()
        try:
            credit = float(request.form.get("credit", "4"))
        except ValueError:
            credit = 0
        files = request.files.getlist("documents")
        if (
            not title
            or len(title) > 120
            or not 0 < credit <= 100
            or not 1 <= len(files) <= 10
        ):
            return jsonify(
                error="Add a module name, valid credits and 1–10 documents."
            ), 400
        staged = []
        for upload in files:
            content = upload.read(10 * 1024 * 1024 + 1)
            if not content or len(content) > 10 * 1024 * 1024:
                return jsonify(error="Each document must be no larger than 10 MB."), 400
            if content.startswith(b"%PDF-"):
                suffix = ".pdf"
            else:
                import io

                try:
                    with Image.open(io.BytesIO(content)) as image:
                        if image.format not in {"PNG", "JPEG"}:
                            raise ValueError()
                        suffix = ".png" if image.format == "PNG" else ".jpg"
                        image.verify()
                except Exception:
                    return jsonify(error="Use PDF, PNG or JPEG documents."), 400
            staged.append((content, suffix))
        digests = [hashlib.sha256(content).digest() for content, _ in staged]
        if len(digests) != len(set(digests)):
            return jsonify(
                error="The same document was added twice. Remove the duplicate and try again."
            ), 400
        if not slots.acquire(blocking=False):
            return jsonify(
                error="Two modules are already being processed. Please wait for one to finish."
            ), 429
        job_id = uuid.uuid4().hex
        folder = root / job_id
        try:
            folder.mkdir()
            paths = []
            for i, (content, suffix) in enumerate(staged):
                path = folder / f"upload-{i}{suffix}"
                path.write_bytes(content)
                paths.append(path)
            with lock:
                jobs[job_id] = {
                    "stage": "queued",
                    "message": "Waiting to read your documents…",
                    "module": title,
                    "filenames": [
                        (upload.filename or "Document")
                        .replace("\\", "/")
                        .split("/")[-1][:255]
                        for upload in files
                    ],
                }
            update(job_id)
            executor.submit(worker, job_id, paths, title, credit, folder)
        except Exception:
            slots.release()
            raise
        return jsonify(id=job_id), 202

    @app.get("/jobs/<job_id>")
    def status(job_id):
        with lock:
            data = jobs.get(job_id)
            if data is None:
                return jsonify(
                    error="This document session is no longer available."
                ), 404
            return jsonify(data)

    @app.get("/jobs/<job_id>/sources")
    def sources(job_id):
        with lock:
            if job_id not in jobs or jobs[job_id]["stage"] != "ready":
                return jsonify(error="Document is not ready."), 404
        folder = root / job_id
        records = []
        for index, source in enumerate(sorted(folder.glob("source-*"))):
            doc = json.loads((source / "document.json").read_text())
            original = next(source.glob("original.*"))
            prefix = f"/jobs/{job_id}/files/{source.name}/"
            records.append(
                {
                    "sha": doc["document_sha256"],
                    "name": jobs[job_id].get("filenames", [original.name] * 10)[index],
                    "original": prefix + original.name,
                    "pages": {
                        number: prefix + name
                        for number, name in doc.get("page_images", {}).items()
                    },
                }
            )
        return jsonify(records)

    @app.get("/jobs/<job_id>/files/<path:filename>")
    def artifact(job_id, filename):
        with lock:
            if job_id not in jobs or jobs[job_id]["stage"] != "ready":
                return jsonify(error="Document is not ready."), 404
        return send_from_directory(root / job_id, filename)

    @app.errorhandler(413)
    def oversized(_error):
        return jsonify(error="Upload fewer documents; the total limit is 50 MB."), 413

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--data-dir")
    parser.add_argument("--docling-url", default="http://127.0.0.1:15001")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="stackplan-document-demo-") as root:
        app = create_demo(args.data_dir or root, args.docling_url)
        try:
            app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
        finally:
            app.extensions["document_demo"]["executor"].shutdown(wait=True)


if __name__ == "__main__":
    main()
