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
import time
import uuid
import json
import re
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
        # Reflection-driven evolution
        self.app.router.add_post("/reflect", self.reflect_handler)
        self.app.router.add_post("/feedback", self.feedback_handler)
        self.app.router.add_get("/logs", self.logs_handler)
        # /mutate is now restricted to orchestrator use
        self.app.router.add_post("/mutate", self.mutate_handler)

    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        from evo_bootstrap.reflector import get_log_stats
        log_stats = get_log_stats()

        return web.json_response({
            "status": "alive",
            "organism_id": self.organism_id,
            "genome_branch": self.genome_branch,
            "generation": self.generation,
            "deepagents_loaded": self.agent is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_stats": log_stats
        })

    async def task_handler(self, request: web.Request) -> web.Response:
        """Execute a task using the deepagent"""
        if self.agent is None:
            return web.json_response(
                {"error": "Agent not initialized"},
                status=503
            )

        from evo_bootstrap.reflector import record_task_execution

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        try:
            data = await request.json()
            task = data.get("task", "")

            logger.info(f"Executing task {task_id}: {task[:100]}...")

            # Run the agent
            result = await self._run_agent(task)

            # Record successful execution
            duration_ms = int((time.time() - start_time) * 1000)
            record_task_execution(
                task_id=task_id,
                task_summary=task,
                duration_ms=duration_ms,
                status="success"
            )

            return web.json_response({
                "status": "completed",
                "task_id": task_id,
                "result": result,
                "duration_ms": duration_ms,
                "organism_id": self.organism_id,
                "generation": self.generation
            })

        except Exception as e:
            logger.exception("Task execution failed")

            # Record failed execution
            duration_ms = int((time.time() - start_time) * 1000)
            record_task_execution(
                task_id=task_id,
                task_summary=data.get("task", "unknown") if 'data' in dir() else "unknown",
                duration_ms=duration_ms,
                status="failure",
                error={
                    "type": type(e).__name__,
                    "message": str(e)
                }
            )

            return web.json_response(
                {"error": str(e), "task_id": task_id},
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

    async def reflect_handler(self, request: web.Request) -> web.Response:
        """
        触发反思流程，分析执行日志并可能生成改进 Proposal。

        只应在 Agent idle 时调用，不影响正在执行的任务。
        这是反思驱动进化的核心入口。
        """
        from evo_bootstrap.reflector import (
            extract_issues_for_reflection,
            build_reflection_prompt
        )
        from evo_bootstrap.proposer import (
            validate_proposal,
            create_github_issue,
            save_proposal_locally
        )

        try:
            data = await request.json() if request.body_exists else {}
            lookback_hours = data.get("lookback_hours", 24)
            min_occurrences = data.get("min_occurrences", 2)

            # 1. 提取问题
            issues = extract_issues_for_reflection(
                lookback_hours=lookback_hours,
                min_occurrences=min_occurrences
            )

            if not issues.get("has_issues"):
                return web.json_response({
                    "status": "no_issues",
                    "message": "No significant issues found in recent logs",
                    "summary": issues.get("summary", {})
                })

            # 2. 让 Agent 分析并生成 Proposal
            reflection_prompt = build_reflection_prompt(issues)
            logger.info("Running reflection analysis...")

            analysis_result = await self._run_agent(reflection_prompt)

            # 3. 解析 Agent 的响应
            try:
                # 尝试多种方式提取 JSON
                analysis = None

                # 方法1: 尝试提取 ```json ... ``` 代码块
                code_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', analysis_result)
                if code_block_match:
                    try:
                        analysis = json.loads(code_block_match.group(1))
                    except json.JSONDecodeError:
                        pass

                # 方法2: 尝试提取最后一个完整的 JSON 对象
                if not analysis:
                    # 找所有可能的 JSON 对象
                    json_matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', analysis_result)
                    for match in reversed(json_matches):
                        try:
                            parsed = json.loads(match)
                            if "should_propose" in parsed:
                                analysis = parsed
                                break
                        except json.JSONDecodeError:
                            continue

                # 方法3: 尝试解析整个响应
                if not analysis:
                    try:
                        analysis = json.loads(analysis_result)
                    except json.JSONDecodeError:
                        pass

                if not analysis:
                    return web.json_response({
                        "status": "analysis_failed",
                        "message": "Could not parse agent response as JSON",
                        "raw_response": analysis_result[:1000]
                    })
            except Exception as e:
                return web.json_response({
                    "status": "analysis_failed",
                    "message": f"Parse error: {e}",
                    "raw_response": analysis_result[:1000]
                })

            # 4. 如果 Agent 建议提出 Proposal
            if analysis.get("should_propose") and analysis.get("proposal"):
                proposal = validate_proposal(analysis["proposal"])

                # 保存本地
                local_path = await save_proposal_locally(
                    proposal=proposal,
                    organism_id=self.organism_id,
                    generation=self.generation
                )

                # 尝试创建 GitHub Issue
                try:
                    issue_result = await create_github_issue(
                        proposal=proposal,
                        organism_id=self.organism_id,
                        generation=self.generation,
                        genome_branch=self.genome_branch
                    )
                    return web.json_response({
                        "status": "proposal_created",
                        "reasoning": analysis.get("reasoning"),
                        "issue_url": issue_result["issue_url"],
                        "issue_number": issue_result["issue_number"],
                        "local_path": local_path
                    })
                except Exception as gh_error:
                    return web.json_response({
                        "status": "proposal_created_locally",
                        "reasoning": analysis.get("reasoning"),
                        "local_path": local_path,
                        "github_error": str(gh_error)
                    })
            else:
                return web.json_response({
                    "status": "no_proposal",
                    "reasoning": analysis.get("reasoning", "No valuable improvements identified"),
                    "issues_analyzed": issues["summary"]
                })

        except Exception as e:
            logger.exception("Reflection failed")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def feedback_handler(self, request: web.Request) -> web.Response:
        """
        记录用户对任务执行的反馈。

        用于收集负反馈，作为反思的数据来源。
        """
        from evo_bootstrap.reflector import record_user_feedback

        try:
            data = await request.json()
            task_id = data.get("task_id")
            feedback_type = data.get("type", "neutral")  # positive | negative | neutral
            message = data.get("message", "")

            if not task_id:
                return web.json_response(
                    {"error": "task_id is required"},
                    status=400
                )

            record_user_feedback(task_id, feedback_type, message)

            return web.json_response({
                "status": "recorded",
                "task_id": task_id,
                "feedback_type": feedback_type
            })

        except Exception as e:
            logger.exception("Failed to record feedback")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def logs_handler(self, request: web.Request) -> web.Response:
        """返回执行日志摘要"""
        from evo_bootstrap.reflector import load_execution_log

        log = load_execution_log()
        return web.json_response({
            "organism_id": self.organism_id,
            "performance": log["performance"],
            "recent_errors": log["errors"][-10:],
            "recent_tasks": log["tasks"][-20:]
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
