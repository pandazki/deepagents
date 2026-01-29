#!/bin/bash
set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║           EvoAgent Bootstrap - Starting                      ║"
echo "╚════════════════════════════════════════════════════════════╝"

# Environment variables
REPO_URL="https://${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"
BRANCH="${GENOME_BRANCH:-evo-seed}"
ORGANISM="${ORGANISM_ID:-org_unknown}"

echo ""
echo "📋 Configuration:"
echo "   Repository: ${GITHUB_REPO}"
echo "   Branch:     ${BRANCH}"
echo "   Organism:   ${ORGANISM}"
echo ""

cd /workspace

# Check if already cloned
if [ -d ".git" ]; then
    echo "🔄 Genome already present, pulling latest..."
    git fetch origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
    echo "   Updated to latest $BRANCH"
else
    # Clone fresh
    echo "🧬 Cloning genome from ${GITHUB_REPO}:${BRANCH}..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" .
fi

# Configure git for future commits (mutations)
git config user.email "evo-agent@evolution.local"
git config user.name "EvoAgent-${ORGANISM}"

# Show genome info
echo ""
echo "📁 Genome structure:"
if [ -d "libs/deepagents/deepagents" ]; then
    ls -la libs/deepagents/deepagents/
else
    echo "   ⚠️  Warning: libs/deepagents/deepagents/ not found"
    echo "   This might be a fresh evo-seed branch"
fi

# Install genome dependencies (deepagents)
echo ""
echo "📦 Installing genome dependencies..."
if [ -f "libs/deepagents/pyproject.toml" ]; then
    pip install -e libs/deepagents/
elif [ -f "libs/deepagents/requirements.txt" ]; then
    pip install -r libs/deepagents/requirements.txt
else
    echo "   ⚠️  No dependency file found, installing deepagents from PyPI as fallback"
    pip install deepagents langchain-anthropic
fi

# Show CHRONICLE if exists
echo ""
if [ -f "libs/deepagents/deepagents/CHRONICLE.yaml" ]; then
    echo "📜 Evolution Chronicle:"
    cat libs/deepagents/deepagents/CHRONICLE.yaml
else
    echo "📜 No chronicle yet (Generation 0)"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║           Starting EvoAgent Bootstrap Runner                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Start the bootstrap runner
exec python -m evo_bootstrap.runner
