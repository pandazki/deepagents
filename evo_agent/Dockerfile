# EvoAgent Sandbox Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install uv

# Create workspace
WORKDIR /workspace

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN uv pip install --system -r requirements.txt

# Copy agent code
COPY . /workspace/evo_agent/

# Set environment variables (will be overridden at runtime)
ENV ORGANISM_ID=default
ENV GENOME_BRANCH=evo-seed

# Expose port
EXPOSE 8080

# Entry point
CMD ["python", "-m", "evo_agent.agent", "--port", "8080"]
