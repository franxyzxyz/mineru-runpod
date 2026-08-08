# MinerU on RunPod serverless

Stage 1a of the extraction pipeline (`docs/mineru_service_plan.md`): a GPU worker that
turns a PDF into MinerU's `content_list` blocks + crop images. Serverless with
`workersMin: 0`, so it costs nothing until a job is submitted.

Upstream: <https://github.com/opendatalab/MinerU> — `mineru[pipeline]`, no fork, no
patches. `handler.py` is the only code here; it calls `do_parse` and returns the
artifact instead of writing it to disk.

## Contract

```
POST https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/runsync
Authorization: Bearer $RUNPOD_API_KEY

{"input": {"pdf_base64": "...", "lang": "en"}}       # or {"pdf_url": "https://..."}

→ {"output": {"blocks": [...], "images": {"images/a.jpg": "<b64>"},
              "pages": 6, "dropped_images": 0, "duration_ms": 18234}}
```

`{blocks, images}` is exactly the body of `POST /papers/:id/multipass`, so the caller
pipes the output straight through — see `tools/mineru-run.ts`.

## Deploy

The image must be linux/amd64 and pullable by RunPod, so GitHub Actions builds it:

1. Build-host repo — <https://github.com/franxyzxyz/mineru-runpod> — holds `Dockerfile`,
   `handler.py` and `build.yml` (as `.github/workflows/build.yml`). This directory is the
   source of truth; push changes with:

   ```bash
   services/mineru/push-build-host.sh
   ```

2. Actions publishes `ghcr.io/franxyzxyz/mineru-runpod:latest` (~40-60 min: torch,
   CUDA, and the baked pipeline weights). The package must be **public** for RunPod to
   pull it without registry credentials.

3. The endpoint is created from that image (GPU pools `ADA_24`/`AMPERE_24`/`AMPERE_48`,
   min 0 / max 3, FlashBoot on). Live: **`m7frm4fstshkpm`** (`foxbook-mineru`), in
   `RUNPOD_ENDPOINT_ID`. Point it at the commit tag, not `:latest`, after a rebuild —
   workers cache `:latest` by digest and a stale one will happily serve the old code.

Smoke test (~85 s cold, ~6 s warm):

```bash
curl -s -X POST https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/runsync \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":{"pdf_url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}}'
```

`services/mineru/handler_test.py` runs the same parse path against a local mineru, which
is the cheap way to catch breakage before a 5-minute build and a GPU cold start.

Model weights are baked into the image, so a cold start is model *load* (~30-60 s), not
download. Bumping `MINERU_VERSION` in the Dockerfile rebuilds and republishes.
