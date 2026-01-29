# EvoAgent Bootstrap Dockerfile
# This image provides the FIXED bootstrap environment
# The GENOME (deepagents) will be cloned at runtime

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create workspace
WORKDIR /workspace

# Install bootstrap dependencies (fixed)
COPY requirements.txt /bootstrap/requirements.txt
RUN pip install --no-cache-dir -r /bootstrap/requirements.txt

# Copy bootstrap code (fixed, does not evolve)
COPY runner.py /bootstrap/runner.py
COPY mutator.py /bootstrap/mutator.py
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
