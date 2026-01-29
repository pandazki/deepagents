# EvoAgent Bootstrap Dockerfile
# This image provides the FIXED bootstrap environment
# The GENOME (deepagents) will be cloned at runtime

FROM python:3.11-slim

# Install system dependencies including GitHub CLI
RUN apt-get update && apt-get install -y \
    git \
    curl \
    gnupg \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Create workspace
WORKDIR /workspace

# Install bootstrap dependencies (fixed)
COPY requirements.txt /bootstrap/requirements.txt
RUN pip install --no-cache-dir -r /bootstrap/requirements.txt

# Copy bootstrap code (fixed, does not evolve)
COPY runner.py /bootstrap/runner.py
COPY mutator.py /bootstrap/mutator.py
COPY proposer.py /bootstrap/proposer.py
COPY __init__.py /bootstrap/__init__.py

# Make bootstrap importable
ENV PYTHONPATH="/bootstrap:${PYTHONPATH}"

# Expose port
EXPOSE 8080

# Entrypoint script that:
# 1. Clones the genome (deepagents repo with specific branch)
# 2. Installs genome dependencies
# 3. Starts the bootstrap runner
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
