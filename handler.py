# RunPod serverless handler around upstream MinerU (github.com/opendatalab/MinerU).
#
# in:  {"pdf_base64": "..."} or {"pdf_url": "https://..."}   (+ lang, backend, pages)
# out: {"blocks": [...], "images": {"images/x.jpg": "<b64>"}, "pages": n, "duration_ms": n}
#
# The output shape is exactly the body of POST /papers/:id/multipass, so the caller
# pipes it straight through (see tools/mineru-run.ts).
import base64
import glob
import json
import os
import tempfile
import time
import urllib.request

import runpod
from mineru.cli.common import do_parse

# ponytail: crops ride back inside the job result, so no R2 credentials live here and
# the caller needs no second fetch. Ceiling = RunPod's ~10 MB result cap; a 5-10 page
# paper is well under it. Past that, upload crops to R2 in-handler and return keys.
IMAGE_BUDGET_BYTES = 8 * 1024 * 1024
PDF_LIMIT_BYTES = 32 * 1024 * 1024


def _load_pdf(inp):
    if inp.get("pdf_base64"):
        return base64.b64decode(inp["pdf_base64"])
    url = inp.get("pdf_url")
    if not url:
        raise ValueError("input needs pdf_base64 or pdf_url")
    if not url.startswith(("http://", "https://")):
        raise ValueError("pdf_url must be http(s)")
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 (scheme checked)
        return r.read(PDF_LIMIT_BYTES + 1)


def handler(job):
    inp = job.get("input") or {}
    t0 = time.time()
    try:
        pdf = _load_pdf(inp)
    except Exception as e:
        return {"error": f"pdf fetch failed: {e}"}
    if not pdf:
        return {"error": "empty pdf"}
    if len(pdf) > PDF_LIMIT_BYTES:
        return {"error": f"pdf larger than {PDF_LIMIT_BYTES} bytes"}

    with tempfile.TemporaryDirectory() as out:
        do_parse(
            output_dir=out,
            pdf_file_names=["paper"],
            pdf_bytes_list=[pdf],
            p_lang_list=[inp.get("lang", "en")],
            backend=inp.get("backend", "pipeline"),
            end_page_id=inp.get("end_page_id"),
            # content_list + crops are all we consume; skip the debug artifacts.
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=False,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=True,
        )
        found = glob.glob(f"{out}/**/*_content_list.json", recursive=True)
        if not found:
            return {"error": "mineru produced no content_list.json"}
        with open(found[0], encoding="utf-8") as f:
            blocks = json.load(f)
        base_dir = os.path.dirname(found[0])

        images, dropped, used = {}, 0, 0
        for b in blocks:
            p = b.get("img_path")
            if not p or p in images:
                continue
            path = os.path.join(base_dir, p)
            if not os.path.exists(path):
                dropped += 1
                continue
            size = os.path.getsize(path)
            if used + size > IMAGE_BUDGET_BYTES:
                dropped += 1
                continue
            with open(path, "rb") as f:
                images[p] = base64.b64encode(f.read()).decode()
            used += size

    return {
        "blocks": blocks,
        "images": images,
        "pages": max((b.get("page_idx", 0) for b in blocks), default=-1) + 1,
        "dropped_images": dropped,
        "duration_ms": int((time.time() - t0) * 1000),
    }


# The main guard is load-bearing: mineru rasterises pages in a *spawn* process pool, and
# a spawned child re-imports this file as __main__ — unguarded, every child boots a second
# serverless worker and the container is torn down mid-job.
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
