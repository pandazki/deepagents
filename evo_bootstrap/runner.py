#!/usr/bin/env python3
"""
EvoAgent Bootstrap Runner

This is the FIXED bootstrap layer - it does NOT evolve.
Its only job is:
1. Load the deepagents library (which CAN evolve)
2. Create an agent using create_deep_agent()
3. Start a server to receive tasks
4. Expose endpoints for evolution proposals

The GENOME (deepagents library) is what evolves, not this bootstrap.
Agent 提出进化 Proposal，由外部 Coding Agent 实现。
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone

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
    - Serves HTTP endpoints for tasks and proposals
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
        self.app.router.add_post("/propose", self.propose_handler)
        self.app.router.add_get("/proposals", self.list_proposals_handler)
        self.app.router.add_get("/genome", self.genome_handler)
        # /mutate is now restricted to orchestrator use
        self.app.router.add_post("/mutate", self.mutate_handler)

    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        return web.json_response({
            "status": "alive",
            "organism_id": self.organism_id,
            "genome_branch": self.genome_branch,
            "generation": self.generation,
            "deepagents_loaded": self.agent is not None,
            "timestamp": datetime.now(timezone.utc).isoformat()
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

    async def propose_handler(self, request: web.Request) -> web.Response:
        """
        Submit an evolution proposal.

        Agent 发现问题后，通过此端点提交进化提案。
        提案会创建 GitHub Issue，由人类或 Orchestrator 审核后，
        由专业 Coding Agent (如 Claude Code) 实现。
        """
        try:
            data = await request.json()

            # Import proposer
            from evo_bootstrap.proposer import (
                validate_proposal,
                create_github_issue,
                save_proposal_locally
            )

            # Validate proposal format
            proposal = validate_proposal(data)

            # Save locally first (backup)
            local_path = await save_proposal_locally(
                proposal=proposal,
                organism_id=self.organism_id,
                generation=self.generation
            )

            # Try to create GitHub Issue
            try:
                issue_result = await create_github_issue(
                    proposal=proposal,
                    organism_id=self.organism_id,
                    generation=self.generation,
                    genome_branch=self.genome_branch
                )

                return web.json_response({
                    "status": "proposed",
                    "issue_number": issue_result["issue_number"],
                    "issue_url": issue_result["issue_url"],
                    "local_path": local_path,
                    "message": "Evolution proposal submitted. Await review and implementation."
                })

            except Exception as gh_error:
                # GitHub failed, but we have local backup
                logger.warning(f"GitHub issue creation failed: {gh_error}")
                return web.json_response({
                    "status": "proposed_locally",
                    "local_path": local_path,
                    "warning": f"GitHub unavailable: {gh_error}",
                    "message": "Proposal saved locally. Will sync to GitHub later."
                })

        except ValueError as e:
            return web.json_response(
                {"error": f"Invalid proposal: {e}"},
                status=400
            )
        except Exception as e:
            logger.exception("Proposal submission failed")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def list_proposals_handler(self, request: web.Request) -> web.Response:
        """List locally saved proposals"""
        try:
            from evo_bootstrap.proposer import list_local_proposals
            proposals = await list_local_proposals()
            return web.json_response({
                "organism_id": self.organism_id,
                "proposals": proposals
            })
        except Exception as e:
            logger.exception("Failed to list proposals")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def mutate_handler(self, request: web.Request) -> web.Response:
        """
        Trigger a mutation (commit changes and create new branch).

        RESTRICTED: This endpoint should only be called by the Orchestrator
        or Coding Agent after implementing an approved proposal.

        Agents should use /propose to submit evolution ideas.
        """
        # Check for orchestrator token
        auth_header = request.headers.get("Authorization", "")
        orchestrator_token = os.environ.get("ORCHESTRATOR_TOKEN", "")

        if orchestrator_token and auth_header != f"Bearer {orchestrator_token}":
            return web.json_response({
                "error": "Mutation restricted to orchestrator",
                "hint": "Use POST /propose to submit evolution proposals"
            }, status=403)

        try:
            data = await request.json()
            message = data.get("message", "Evolution mutation")
            proposal_id = data.get("proposal_id")  # Link to approved proposal

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
                "parent_generation": self.generation,
                "proposal_id": proposal_id
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
        backend = FilesystemBackend(root_dir=str(WORKSPACE))

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
        """Build system prompt that tells agent about itself and evolution process"""
        return f"""You are an evolving AI agent (Organism: {self.organism_id}, Generation: {self.generation}).

## Your Identity

- Organism ID: {self.organism_id}
- Generation: {self.generation}
- Genome Branch: {self.genome_branch}
- Genome Location: /workspace/libs/deepagents/deepagents/

## Your Capabilities

You can read your own source code to understand how you work:
- graph.py: How you are created
- middleware/filesystem.py: Your file operation tools
- middleware/subagents.py: How you spawn sub-agents
- middleware/skills.py: How you load skills
- backends/*.py: How you interact with storage

## Evolution Process (IMPORTANT)

You have the ability to PROPOSE improvements to yourself, but you do NOT directly modify your code.

When you identify problems or improvements:

1. **Analyze** the issue thoroughly:
   - What problem are you facing?
   - What evidence do you have? (logs, errors, observations)
   - Read relevant source code to understand the root cause

2. **Research** potential solutions:
   - What approaches could solve this?
   - What are the tradeoffs?

3. **Submit a Proposal** via POST /propose with:
   ```json
   {{
     "title": "Brief description of improvement",
     "problem_description": "Detailed problem explanation",
     "evidence": [
       {{"type": "self_observation", "summary": "...", "file": "...", "line": ...}},
       {{"type": "log", "id": "...", "summary": "..."}}
     ],
     "solution_approach": "How to solve it",
     "target_files": [
       {{"path": "middleware/filesystem.py", "changes": "Add caching layer"}}
     ],
     "pseudo_code": "Optional implementation sketch",
     "risks": [
       {{"risk": "Memory usage", "severity": "medium", "mitigation": "LRU cache"}}
     ],
     "success_metrics": [
       {{"metric": "p95 latency", "current": "500ms", "target": "<100ms"}}
     ]
   }}
   ```

4. **A human or Orchestrator** will review your proposal
5. **A specialized Coding Agent** (like Claude Code) will implement approved proposals
6. **A new generation** will be created with the improvements

This separation ensures:
- You focus on THINKING and ANALYZING
- Professional tools handle CODING
- Humans/AI maintain oversight

## Why This Matters

You are part of an evolutionary system. Your proposals contribute to collective intelligence.
Multiple agents facing similar problems will have their proposals aggregated, revealing
patterns and prioritizing the most impactful improvements.

Think of yourself as a researcher proposing hypotheses, not a developer shipping code.
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
