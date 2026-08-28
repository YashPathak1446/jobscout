# JobScout, hosted.
#
# Three stages so the ~1 GB of TeX Live is not carried through a node install,
# and so the frontend's node_modules never reaches the running image.
#
# The genuine unknown this exists to answer is whether pdflatex compiles the
# real template inside a container at all. Everything else here is plumbing;
# that one line is the phase.

# ---------------------------------------------------------------- web ----
FROM node:22-slim AS web

WORKDIR /web
# package files first: this layer is cached unless dependencies actually
# change, so an edit to a component does not reinstall node_modules.
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install

COPY web/ ./
# Vite writes to /web/dist. The client calls /api by relative path — there is
# no hostname compiled in — which is what lets the API serve this build from
# its own origin instead of needing CORS and a second domain.
RUN npm run build


# --------------------------------------------------------------- runtime ----
FROM python:3.12-slim AS runtime

# texlive-latex-extra carries the packages the resume template uses beyond
# base LaTeX. It is the bulk of the image and it is not optional: without it
# pdflatex exits non-zero on the preamble and every resume comes back
# "skipped", which the pipeline treats as a soft failure — so the app would
# look like it worked and produce no PDFs.
#
# --no-install-recommends keeps the doc/font trees out; recommends on
# texlive pull in several hundred MB of documentation nobody in a container
# will read.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source, for the same layer-caching reason as above.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/ ./agents/
COPY api/ ./api/
COPY scripts/ ./scripts/
COPY tools/ ./tools/
COPY config.py app.py ./

COPY --from=web /web/dist ./web/dist

# Where the app keeps things that must outlive a deploy: runs.db, jobs.db, the
# caches, and uploaded master resumes. A Fly volume mounts here.
#
# `data/` is the one directory whose loss is not recoverable by rebuilding, so
# it is the one that must not live in the image. An image is replaced on every
# deploy; a volume is not.
ENV JOBSCOUT_HOME=/data
VOLUME ["/data"]

# `/api/file` resolves downloads relative to the working directory, so this
# has to match where outputs land. Stated rather than assumed: if WORKDIR and
# that resolution ever disagree, every download 404s and nothing says why.
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# One worker on purpose. `start_run` backgrounds the pipeline in an in-process
# thread and reports progress through data/runs.db, so a second worker would
# be a second process that cannot see the first one's threads — the run would
# start under one and be invisible to the other. Multiple workers arrive with
# a real queue, not before.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
