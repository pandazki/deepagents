#!/usr/bin/env python3
"""
EvoAgent Mutator

This is the FIXED mutation layer - it does NOT evolve.
Its only job is:
1. Commit code changes made by the agent
2. Create a new branch (new generation)
3. Push to remote
4. Notify orchestrator

The agent modifies its own source code (the genome).
This module handles the git operations to persist those changes.
"""

import os
import subprocess
import asyncio
import logging
import uuid
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("evo_mutator")

WORKSPACE = Path("/workspace")
CHRONICLE_PATH = WORKSPACE / "libs" / "deepagents" / "deepagents" / "CHRONICLE.yaml"


def generate_mutation_id() -> str:
    """Generate a short unique ID for the mutation"""
    return uuid.uuid4().hex[:6]


def run_git(*args) -> subprocess.CompletedProcess:
    """Run a git command in the workspace"""
    result = subprocess.run(
        ["git", *args],
        cwd=WORKSPACE,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        logger.error(f"Git command failed: git {' '.join(args)}")
        logger.error(f"stderr: {result.stderr}")
        raise RuntimeError(f"Git error: {result.stderr}")
    return result


def update_chronicle(
    new_branch: str,
    parent_branch: str,
    generation: int,
    message: str,
    organism_id: str
) -> None:
    """Update CHRONICLE.yaml with the new mutation"""

    # Load existing or create new
    if CHRONICLE_PATH.exists():
        with open(CHRONICLE_PATH) as f:
            chronicle = yaml.safe_load(f) or {}
    else:
        chronicle = {}

    # Update generation
    chronicle["generation"] = generation + 1

    # Add mutation record
    mutations = chronicle.get("mutations", [])
    mutations.append({
        "from_branch": parent_branch,
        "to_branch": new_branch,
        "from_generation": generation,
        "to_generation": generation + 1,
        "timestamp": datetime.utcnow().isoformat(),
        "organism_id": organism_id,
        "message": message
    })
    chronicle["mutations"] = mutations

    # Update metadata
    chronicle["last_mutation"] = datetime.utcnow().isoformat()
    chronicle["organism_id"] = organism_id
    chronicle["branch"] = new_branch

    # Ensure directory exists
    CHRONICLE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Write back
    with open(CHRONICLE_PATH, "w") as f:
        yaml.dump(chronicle, f, default_flow_style=False, allow_unicode=True)


async def commit_and_branch(
    message: str,
    generation: int,
    organism_id: str
) -> str:
    """
    Commit current changes and create a new branch (new generation).

    This is the core mutation operation:
    1. Stage all changes in the genome
    2. Update CHRONICLE.yaml with mutation info
    3. Commit changes
    4. Create new branch
    5. Push to remote
    6. Return the new branch name

    Args:
        message: Mutation description
        generation: Current generation number
        organism_id: Organism identifier

    Returns:
        New branch name (e.g., "gen2_abc123")
    """
    loop = asyncio.get_event_loop()

    # Generate new branch name
    mutation_id = generate_mutation_id()
    new_generation = generation + 1
    new_branch = f"gen{new_generation}_{mutation_id}"

    logger.info(f"Starting mutation: gen{generation} -> {new_branch}")

    # Get current branch
    result = await loop.run_in_executor(
        None, lambda: run_git("rev-parse", "--abbrev-ref", "HEAD")
    )
    parent_branch = result.stdout.strip()

    # Update chronicle first
    await loop.run_in_executor(
        None,
        lambda: update_chronicle(
            new_branch=new_branch,
            parent_branch=parent_branch,
            generation=generation,
            message=message,
            organism_id=organism_id
        )
    )

    # Stage all changes in the genome directory
    await loop.run_in_executor(
        None, lambda: run_git("add", "libs/deepagents/")
    )

    # Check if there are changes to commit
    result = await loop.run_in_executor(
        None, lambda: run_git("status", "--porcelain")
    )

    if not result.stdout.strip():
        logger.warning("No changes to commit")
        raise RuntimeError("No changes detected in genome")

    # Commit
    commit_message = f"""[Gen {new_generation}] {message}

Organism: {organism_id}
Parent: {parent_branch} (gen {generation})
Mutation ID: {mutation_id}
"""
    await loop.run_in_executor(
        None, lambda: run_git("commit", "-m", commit_message)
    )

    # Create new branch
    await loop.run_in_executor(
        None, lambda: run_git("checkout", "-b", new_branch)
    )

    # Push to remote
    await loop.run_in_executor(
        None, lambda: run_git("push", "-u", "origin", new_branch)
    )

    logger.info(f"Mutation complete: {new_branch}")

    # TODO: Notify orchestrator about new offspring
    # await notify_orchestrator(new_branch, parent_branch, organism_id)

    return new_branch


async def get_mutation_history() -> list:
    """Get the mutation history from CHRONICLE.yaml"""
    if not CHRONICLE_PATH.exists():
        return []

    with open(CHRONICLE_PATH) as f:
        chronicle = yaml.safe_load(f) or {}

    return chronicle.get("mutations", [])


async def get_current_genome_status() -> dict:
    """Get the current status of the genome (git status)"""
    loop = asyncio.get_event_loop()

    # Get current branch
    result = await loop.run_in_executor(
        None, lambda: run_git("rev-parse", "--abbrev-ref", "HEAD")
    )
    branch = result.stdout.strip()

    # Get status
    result = await loop.run_in_executor(
        None, lambda: run_git("status", "--porcelain")
    )
    changes = result.stdout.strip().split("\n") if result.stdout.strip() else []

    # Get last commit
    result = await loop.run_in_executor(
        None, lambda: run_git("log", "-1", "--format=%H %s")
    )
    last_commit = result.stdout.strip()

    return {
        "branch": branch,
        "uncommitted_changes": len(changes),
        "changed_files": changes[:10],  # First 10 only
        "last_commit": last_commit
    }
