# Multi-stage build using Astral uv (builder) and a minimal Alpine final image.
# Requires Docker BuildKit for the --mount cache/bind syntax used during build.

# Builder: use Astral's uv image for Alpine (includes uv + tooling)
FROM ghcr.io/astral-sh/uv:alpine3.23 AS builder

# Optimize for standalone Python builds
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV UV_NO_DEV=1
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed

# Install the managed Python version matching pyproject (>=3.14). Pin to 3.14 for reproducibility.
RUN uv python install 3.14

WORKDIR /app

# Use BuildKit mounts for caching and deterministic installs. This expects uv.lock to exist for locked installs.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock,readOnly \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml,readOnly \
    uv sync --locked --no-install-project

# Copy project sources and install the project into the environment
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Final: minimal runtime image without uv tooling
FROM dhi.io/alpine-base:3.23

# Copy the standalone Python runtime that uv installed in the builder
COPY --from=builder /python /python

# Copy the application into the final image and set ownership
COPY --from=builder --chown=nonroot:nonroot /app /app

# Ensure the application's virtualenv binaries are first on PATH
ENV PATH="/app/.venv/bin:${PATH}"

USER nonroot
WORKDIR /app

# Default command: run the bot
CMD ["python", "./inlinepixivbot.py"]
