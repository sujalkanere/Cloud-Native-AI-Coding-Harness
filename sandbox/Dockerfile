# Multi-purpose Hardened Linux Sandbox Image
FROM python:3.12-slim-bookworm

# Avoid prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# Install OS packages, build tools, git, curl, and Node 20
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    ca-certificates \
    pkg-config \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && pip install --no-cache-dir pytest \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (uid 1000, gid 1000)
RUN groupadd -g 1000 sandbox \
    && useradd -u 1000 -g sandbox -s /bin/bash -m -d /tmp sandbox

# Pre-create writable tmpfs mount points with proper ownership
RUN mkdir -p /workspace /tmp \
    && chown -R 1000:1000 /workspace /tmp

# Environment variables for tooling under read-only root filesystem
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_CACHE_DIR=/tmp/.cache/pip \
    NPM_CONFIG_CACHE=/tmp/.npm \
    TMPDIR=/tmp \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Run as non-root user
USER 1000:1000
WORKDIR /workspace

# Keep container alive for exec sessions
CMD ["sleep", "infinity"]
