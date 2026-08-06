# MinerU pipeline backend (DocLayout-YOLO + OCR + table/formula) as a RunPod
# serverless worker. Follows upstream's docker/global/Dockerfile, minus vLLM: the
# VLM backends need a 10 GB+ vllm base, and we only consume content_list + crops.
FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

# libgl/glib for opencv, Noto CJK so Chinese papers render in the crops.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 fonts-noto-core fonts-noto-cjk fontconfig \
    && fc-cache -f && apt-get clean && rm -rf /var/lib/apt/lists/*

ARG MINERU_VERSION=3.4.4
RUN pip install --no-cache-dir "mineru[pipeline]==${MINERU_VERSION}" runpod

# Bake the weights so a cold start is model-load, not model-download.
ENV HF_HOME=/models
RUN mineru-models-download -s huggingface -m pipeline

# Set only after the download layer — "local" means "use what's already on disk".
ENV MINERU_MODEL_SOURCE=local PYTHONUNBUFFERED=1

COPY handler.py /handler.py
CMD ["python", "-u", "/handler.py"]
