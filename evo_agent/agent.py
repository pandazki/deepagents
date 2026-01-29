#!/usr/bin/env python3
"""
EvoAgent: 可进化的 AI Agent

核心能力：
1. 执行任务（基于 deepagents）
2. 读取祖先历史（CHRONICLE.yaml）
3. 自我修改并提交到 Git
4. 通知 Orchestrator 产生了新变异

环境变量：
- ANTHROPIC_API_KEY: Claude API 密钥
- GITHUB_TOKEN: GitHub PAT（用于 push）
- GITHUB_REPO: 仓库地址（如 pandazki/deepagents）
- ORGANISM_ID: 当前个体 ID
- GENOME_BRANCH: 当前基因型分支名
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# deepagents imports
try:
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    DEEPAGENTS_AVAILABLE = True
except ImportError:
    DEEPAGENTS_AVAILABLE = False
    print("Warning: deepagents not installed, running in mock mode")


class Chronicle:
    """进化编年史：记录祖先历史和经验教训"""

    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return yaml.safe_load(f) or {}
        return {
            "genome_branch": os.environ.get("GENOME_BRANCH", "unknown"),
            "generation": 0,
            "events": [],
            "learnings": []
        }

    def save(self):
        with open(self.path, "w") as f:
            yaml.dump(self.data, f, allow_unicode=True, default_flow_style=False)

    def record_event(self, event_type: str, data: dict = None):
        self.data.setdefault("events", []).append({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data or {}
        })
        # 只保留最近 100 条
        self.data["events"] = self.data["events"][-100:]
        self.save()

    def add_learning(self, learning: str):
        self.data.setdefault("learnings", []).append(learning)
        # 只保留最近 20 条
        self.data["learnings"] = self.data["learnings"][-20:]
        self.save()

    @property
    def learnings(self) -> list[str]:
        return self.data.get("learnings", [])

    @property
    def generation(self) -> int:
        return self.data.get("generation", 0)


class GitOperations:
    """Git 操作：提交变异到远程仓库"""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.repo = os.environ.get("GITHUB_REPO", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")

    def _git(self, *args) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Git error: {result.stderr}")
        return result.stdout.strip()

    def commit_mutation(
        self,
        mutation_type: str,
        reason: str,
        changed_files: list[str]
    ) -> str:
        """提交变异并返回新的 commit hash"""
        # Stage 文件
        for f in changed_files:
            self._git("add", f)

        # 提交
        message = f"""Mutation: {mutation_type}

Reason: {reason}
Parent: {os.environ.get('GENOME_BRANCH', 'unknown')}
Organism: {os.environ.get('ORGANISM_ID', 'unknown')}
"""
        self._git("commit", "-m", message)

        return self._git("rev-parse", "HEAD")

    def push_new_branch(self, branch_name: str) -> bool:
        """创建新分支并推送到远程"""
        try:
            # 创建新分支
            self._git("checkout", "-b", branch_name)

            # 配置远程（带 token）
            if self.token and self.repo:
                remote_url = f"https://{self.token}@github.com/{self.repo}.git"
                self._git("remote", "set-url", "origin", remote_url)

            # 推送
            self._git("push", "-u", "origin", branch_name)
            return True
        except Exception as e:
            print(f"Push failed: {e}")
            return False


class MutationProposal:
    """变异提议"""
    def __init__(
        self,
        should_modify: bool,
        mutation_type: str = "",
        reason: str = "",
        target_file: str = "",
        changes: list[dict] = None,
        confidence: float = 0.0
    ):
        self.should_modify = should_modify
        self.mutation_type = mutation_type
        self.reason = reason
        self.target_file = target_file
        self.changes = changes or []
        self.confidence = confidence


class EvoAgent:
    """可进化的 AI Agent"""

    def __init__(self, workspace: Path = None):
        self.workspace = workspace or Path("/workspace")
        self.chronicle = Chronicle(self.workspace / "CHRONICLE.yaml")
        self.git = GitOperations(self.workspace)

        self.organism_id = os.environ.get("ORGANISM_ID", "unknown")
        self.genome_branch = os.environ.get("GENOME_BRANCH", "unknown")

        # 初始化 deepagents
        if DEEPAGENTS_AVAILABLE:
            self.backend = FilesystemBackend(root_dir=str(self.workspace))
            self.agent = create_deep_agent(
                model="claude-sonnet-4-5-20250929",
                backend=self.backend,
                system_prompt=self._build_system_prompt()
            )
        else:
            self.agent = None

        # 记录启动事件
        self.chronicle.record_event("spawn", {
            "organism_id": self.organism_id,
            "genome_branch": self.genome_branch
        })

    def _build_system_prompt(self) -> str:
        """构建系统提示词（包含祖先经验）"""
        base = """You are an evolving AI agent. You can learn from your ancestors and improve yourself.

Current workspace: /workspace
You have access to file operations, shell commands, and planning tools.

"""
        # 添加祖先经验
        if self.chronicle.learnings:
            base += "## Learnings from Ancestors\n\n"
            for learning in self.chronicle.learnings[-10:]:
                base += f"- {learning}\n"
            base += "\n"

        return base

    async def execute_task(self, task: dict) -> dict:
        """执行任务"""
        start_time = datetime.now()

        self.chronicle.record_event("task_start", {
            "task_id": task.get("id", "unknown"),
            "description": task.get("description", "")[:100]
        })

        try:
            if self.agent:
                # 使用 deepagents 执行
                result = await self._execute_with_deepagents(task)
            else:
                # Mock 执行
                result = await self._mock_execute(task)

            exec_time = (datetime.now() - start_time).total_seconds() * 1000

            self.chronicle.record_event("task_complete", {
                "task_id": task.get("id"),
                "success": result.get("success", False),
                "exec_time_ms": exec_time
            })

            return {
                "success": True,
                "output": result.get("output", ""),
                "execution_time_ms": exec_time
            }

        except Exception as e:
            self.chronicle.record_event("task_failed", {
                "task_id": task.get("id"),
                "error": str(e)
            })
            return {
                "success": False,
                "error": str(e),
                "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
            }

    async def _execute_with_deepagents(self, task: dict) -> dict:
        """使用 deepagents 执行任务"""
        messages = [{"role": "user", "content": task["description"]}]
        result = await self.agent.ainvoke({"messages": messages})
        return {
            "success": True,
            "output": str(result)
        }

    async def _mock_execute(self, task: dict) -> dict:
        """Mock 执行（测试用）"""
        return {
            "success": True,
            "output": f"[MOCK] Executed: {task.get('description', '')[:50]}"
        }

    async def propose_mutation(self, feedback: dict = None) -> MutationProposal:
        """
        提议自我修改

        基于反馈和祖先经验，提出代码改进建议
        """
        if not self.agent:
            return MutationProposal(should_modify=False, reason="Agent not available")

        # 读取当前代码
        agent_code = (self.workspace / "evo_agent" / "agent.py").read_text()

        prompt = f"""Analyze your own source code and propose improvements.

## Current Code (excerpt)
```python
{agent_code[:3000]}
```

## Recent Feedback
{json.dumps(feedback or {}, indent=2)}

## Learnings from Ancestors
{json.dumps(self.chronicle.learnings, indent=2)}

Based on this, should you modify your code? If yes, propose minimal, targeted changes.

Return JSON:
{{
    "should_modify": true/false,
    "mutation_type": "improve_error_handling" | "optimize_logic" | "add_capability",
    "reason": "Why this change",
    "confidence": 0.0-1.0,
    "target_file": "evo_agent/agent.py",
    "changes": [
        {{"location": "function_name", "description": "what to change"}}
    ]
}}
"""

        try:
            result = await self.agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
            # 解析结果...
            return MutationProposal(
                should_modify=False,
                reason="Mutation proposal parsing not yet implemented"
            )
        except Exception as e:
            return MutationProposal(should_modify=False, reason=str(e))

    async def evolve(self, mutation: MutationProposal) -> Optional[str]:
        """
        执行进化：应用变异并推送到新分支

        返回新分支名，如果失败返回 None
        """
        if not mutation.should_modify:
            return None

        self.chronicle.record_event("mutation_start", {
            "type": mutation.mutation_type,
            "reason": mutation.reason
        })

        try:
            # 1. 应用代码修改（这里简化，实际需要解析 changes）
            # TODO: 实际应用代码修改

            # 2. 更新 CHRONICLE
            self.chronicle.data["generation"] = self.chronicle.generation + 1
            self.chronicle.add_learning(f"Mutation: {mutation.reason}")
            self.chronicle.save()

            # 3. 提交到 Git
            commit_hash = self.git.commit_mutation(
                mutation_type=mutation.mutation_type,
                reason=mutation.reason,
                changed_files=["CHRONICLE.yaml", mutation.target_file]
            )

            # 4. 创建新分支并推送
            new_branch = f"gen{self.chronicle.generation}_{commit_hash[:8]}"
            if self.git.push_new_branch(new_branch):
                self.chronicle.record_event("mutation_complete", {
                    "new_branch": new_branch,
                    "commit": commit_hash
                })
                return new_branch
            else:
                return None

        except Exception as e:
            self.chronicle.record_event("mutation_failed", {"error": str(e)})
            return None


# === HTTP 服务接口 ===

async def run_server(agent: EvoAgent, port: int):
    """运行 HTTP 服务"""
    try:
        from aiohttp import web

        async def handle_task(request):
            task = await request.json()
            result = await agent.execute_task(task)
            return web.json_response(result)

        async def handle_health(request):
            return web.json_response({
                "status": "alive",
                "organism_id": agent.organism_id,
                "genome_branch": agent.genome_branch,
                "generation": agent.chronicle.generation
            })

        async def handle_mutate(request):
            feedback = await request.json()
            proposal = await agent.propose_mutation(feedback)
            if proposal.should_modify:
                new_branch = await agent.evolve(proposal)
                return web.json_response({
                    "mutated": True,
                    "new_branch": new_branch,
                    "reason": proposal.reason
                })
            return web.json_response({
                "mutated": False,
                "reason": proposal.reason
            })

        app = web.Application()
        app.router.add_post("/task", handle_task)
        app.router.add_get("/health", handle_health)
        app.router.add_post("/mutate", handle_mutate)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        print(f"EvoAgent server running on port {port}")
        print(f"  Organism ID: {agent.organism_id}")
        print(f"  Genome: {agent.genome_branch}")
        print(f"  Generation: {agent.chronicle.generation}")

        while True:
            await asyncio.sleep(3600)

    except ImportError:
        print("aiohttp not installed, running in CLI mode")
        await run_cli(agent)


async def run_cli(agent: EvoAgent):
    """CLI 模式（测试/调试用）"""
    print(f"EvoAgent CLI Mode")
    print(f"  Organism ID: {agent.organism_id}")
    print(f"  Genome: {agent.genome_branch}")
    print(f"  Generation: {agent.chronicle.generation}")
    print()
    print("Commands: task <description>, health, mutate, quit")

    while True:
        try:
            line = input("> ").strip()
            if not line:
                continue

            if line == "quit":
                break
            elif line == "health":
                print(json.dumps({
                    "status": "alive",
                    "organism_id": agent.organism_id,
                    "genome_branch": agent.genome_branch,
                    "generation": agent.chronicle.generation
                }, indent=2))
            elif line.startswith("task "):
                desc = line[5:]
                result = await agent.execute_task({"description": desc})
                print(json.dumps(result, indent=2))
            elif line == "mutate":
                proposal = await agent.propose_mutation({})
                print(f"Should modify: {proposal.should_modify}")
                print(f"Reason: {proposal.reason}")
            else:
                print(f"Unknown command: {line}")

        except (EOFError, KeyboardInterrupt):
            break


def main():
    parser = argparse.ArgumentParser(description="EvoAgent - Evolving AI Agent")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--workspace", type=str, default="/workspace", help="Workspace path")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    args = parser.parse_args()

    agent = EvoAgent(workspace=Path(args.workspace))

    if args.cli:
        asyncio.run(run_cli(agent))
    else:
        asyncio.run(run_server(agent, args.port))


if __name__ == "__main__":
    main()
