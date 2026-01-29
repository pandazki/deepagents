#!/usr/bin/env python3
"""
EvoAgent Bootstrap Runner

This is the FIXED bootstrap layer - it does NOT evolve.
Its only job is:
1. Load the deepagents library (which CAN evolve)
2. Create an agent using create_deep_agent()
3. Start a server to receive tasks
4. Expose endpoints for mutation triggers

The GENOME (deepagents library) is what evolves, not this bootstrap.
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

# Add deepagents to path - this is the genome that evolves
WORKSPACE = Path("/workspace")
DEEPAGENTS_PATH = WORKSPACE / "libs" / "deepagents"
sys.path.insert(0, str(DEEPAGENTS_PATH))

from aiohttp import web

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("evo_bootstrap")


class EvoBootstrap:
    """
    Minimal bootstrap for running an evolving deepagent.

    This class is FIXED and does not evolve.
    It only:
    - Loads the deepagents library from /workspace/libs/deepagents
    - Creates an agent using the library's create_deep_agent()
    - Serves HTTP endpoints for tasks and mutations
    """

    def __init__(self):
        self.organism_id = os.environ.get("ORGANISM_ID", "org_unknown")
        self.genome_branch = os.environ.get("GENOME_BRANCH", "evo-seed")
        self.generation = self._load_generation()
        self.agent = None
        self.app = web.Application()
        self._setup_routes()

    def _load_generation(self) -> int:
        """Load generation from CHRONICLE.yaml in the genome"""
        chronicle_path = DEEPAGENTS_PATH / "deepagents" / "CHRONICLE.yaml"
        if chronicle_path.exists():
            import yaml
            with open(chronicle_path) as f:
                data = yaml.safe_load(f)
                return data.get("generation", 0)
        return 0

    def _setup_routes(self):
        """Setup HTTP endpoints"""
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_post("/task", self.task_handler)
        self.app.router.add_post("/mutate", self.mutate_handler)
        self.app.router.add_get("/genome", self.genome_handler)

    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        return web.json_response({
            "status": "alive",
            "organism_id": self.organism_id,
            "genome_branch": self.genome_branch,
            "generation": self.generation,
            "deepagents_loaded": self.agent is not None,
            "timestamp": datetime.utcnow().isoformat()
        })

    async def task_handler(self, request: web.Request) -> web.Response:
        """Execute a task using the deepagent"""
        if self.agent is None:
            return web.json_response(
                {"error": "Agent not initialized"},
                status=503
            )

        try:
            data = await request.json()
            task = data.get("task", "")

            logger.info(f"Executing task: {task[:100]}...")

            # Run the agent
            result = await self._run_agent(task)

            return web.json_response({
                "status": "completed",
                "result": result,
                "organism_id": self.organism_id,
                "generation": self.generation
            })

        except Exception as e:
            logger.exception("Task execution failed")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def mutate_handler(self, request: web.Request) -> web.Response:
        """Trigger a mutation (commit changes and create new branch)"""
        try:
            data = await request.json()
            message = data.get("message", "Evolution mutation")

            # Import mutator (also fixed, not evolved)
            from evo_bootstrap.mutator import commit_and_branch

            new_branch = await commit_and_branch(
                message=message,
                generation=self.generation,
                organism_id=self.organism_id
            )

            return web.json_response({
                "status": "mutated",
                "new_branch": new_branch,
                "parent_branch": self.genome_branch,
                "parent_generation": self.generation
            })

        except Exception as e:
            logger.exception("Mutation failed")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def genome_handler(self, request: web.Request) -> web.Response:
        """Return information about the current genome (deepagents source)"""
        genome_files = []
        deepagents_src = DEEPAGENTS_PATH / "deepagents"

        if deepagents_src.exists():
            for py_file in deepagents_src.rglob("*.py"):
                rel_path = py_file.relative_to(deepagents_src)
                genome_files.append({
                    "path": str(rel_path),
                    "size": py_file.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        py_file.stat().st_mtime
                    ).isoformat()
                })

        return web.json_response({
            "organism_id": self.organism_id,
            "genome_branch": self.genome_branch,
            "generation": self.generation,
            "genome_path": str(deepagents_src),
            "files": genome_files
        })

    async def _run_agent(self, task: str) -> str:
        """Run the deepagent on a task"""
        # Import from the evolving genome
        from deepagents.graph import create_deep_agent
        from deepagents.backends.filesystem import FilesystemBackend
        from langchain_anthropic import ChatAnthropic

        # Create backend with access to workspace (including its own source)
        backend = FilesystemBackend(base_path=str(WORKSPACE))

        # Get model
        model = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

        # Create agent using the genome's factory
        # This is the key: the agent is created by code that CAN evolve
        agent = create_deep_agent(
            model=model,
            backend=backend,
            system_prompt=self._build_system_prompt()
        )

        # Run the agent
        config = {"configurable": {"thread_id": f"{self.organism_id}-task"}}
        messages = [{"role": "user", "content": task}]

        result = await agent.ainvoke({"messages": messages}, config=config)

        # Extract response
        if result.get("messages"):
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):
                return last_msg.content
        return str(result)

    def _build_system_prompt(self) -> str:
        """Build system prompt that tells agent about itself"""
        return f"""You are an evolving AI agent (Organism: {self.organism_id}, Generation: {self.generation}).

Your source code is located at /workspace/libs/deepagents/deepagents/
You have the ability to read and modify your own source code.

Key files you can evolve:
- graph.py: Agent creation factory
- middleware/filesystem.py: File operation tools
- middleware/subagents.py: Subagent spawning logic
- middleware/skills.py: Skill loading system
- backends/*.py: Storage implementations

When you want to evolve (modify your code and create a new generation):
1. Modify files in /workspace/libs/deepagents/deepagents/
2. The changes will be tracked by git
3. A new branch (new generation) can be created via the /mutate endpoint

Current genome branch: {self.genome_branch}
"""

    async def initialize(self):
        """Initialize the agent"""
        try:
            logger.info(f"Initializing EvoBootstrap for {self.organism_id}")
            logger.info(f"Genome branch: {self.genome_branch}")
            logger.info(f"Generation: {self.generation}")

            # Verify deepagents is importable
            import deepagents
            logger.info(f"deepagents loaded from: {deepagents.__file__}")

            self.agent = True  # Mark as ready
            logger.info("Bootstrap initialized successfully")

        except Exception as e:
            logger.exception("Failed to initialize bootstrap")
            raise

    async def run(self, host: str = "0.0.0.0", port: int = 8080):
        """Run the HTTP server"""
        await self.initialize()
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        logger.info(f"Starting server on {host}:{port}")
        await site.start()

        # Keep running
        while True:
            await asyncio.sleep(3600)


async def main():
    bootstrap = EvoBootstrap()
    await bootstrap.run()


if __name__ == "__main__":
    asyncio.run(main())
