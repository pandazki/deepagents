#!/usr/bin/env python3
"""
EvoAgent Proposer

Handles Evolution Proposal creation and GitHub Issue integration.
Agent 提出进化方向，而非直接修改代码。
"""

import os
import asyncio
import logging
import json
import re
from datetime import datetime, timezone
from typing import TypedDict, NotRequired
from pathlib import Path

logger = logging.getLogger("evo_proposer")


class Evidence(TypedDict):
    """进化提案的证据"""
    type: str  # log | task_feedback | self_observation | user_feedback
    id: NotRequired[str]
    summary: str
    file: NotRequired[str]
    line: NotRequired[int]


class Risk(TypedDict):
    """风险评估"""
    risk: str
    severity: str  # low | medium | high | critical
    mitigation: str


class TargetFile(TypedDict):
    """目标文件"""
    path: str
    changes: str


class SuccessMetric(TypedDict):
    """成功指标"""
    metric: str
    current: NotRequired[str]
    target: str


class EvolutionProposal(TypedDict):
    """进化提案结构"""
    title: str
    problem_description: str
    evidence: list[Evidence]
    solution_approach: str
    target_files: list[TargetFile]
    pseudo_code: NotRequired[str]
    risks: list[Risk]
    success_metrics: list[SuccessMetric]
    references: NotRequired[list[dict]]


def validate_proposal(data: dict) -> EvolutionProposal:
    """验证并规范化 Proposal 数据"""
    required_fields = [
        "title",
        "problem_description",
        "solution_approach",
        "target_files"
    ]

    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # 规范化
    proposal: EvolutionProposal = {
        "title": data["title"],
        "problem_description": data["problem_description"],
        "evidence": data.get("evidence", []),
        "solution_approach": data["solution_approach"],
        "target_files": data["target_files"],
        "pseudo_code": data.get("pseudo_code"),
        "risks": data.get("risks", []),
        "success_metrics": data.get("success_metrics", []),
        "references": data.get("references", [])
    }

    return proposal


def format_proposal_as_markdown(
    proposal: EvolutionProposal,
    organism_id: str,
    generation: int,
    genome_branch: str
) -> str:
    """将 Proposal 格式化为 GitHub Issue Markdown"""

    # Evidence section
    evidence_md = ""
    if proposal["evidence"]:
        evidence_md = "### Evidence\n\n"
        for e in proposal["evidence"]:
            evidence_md += f"- **{e['type']}**: {e['summary']}"
            if e.get("file"):
                evidence_md += f" (`{e['file']}:{e.get('line', '')}`)"
            evidence_md += "\n"

    # Target files section
    target_files_md = "### Target Files\n\n"
    for tf in proposal["target_files"]:
        target_files_md += f"- `{tf['path']}`: {tf['changes']}\n"

    # Pseudo code section
    pseudo_code_md = ""
    if proposal.get("pseudo_code"):
        pseudo_code_md = f"""### Proposed Implementation (Pseudo Code)

```python
{proposal['pseudo_code']}
```

"""

    # Risks section
    risks_md = ""
    if proposal["risks"]:
        risks_md = "### Risk Assessment\n\n"
        risks_md += "| Risk | Severity | Mitigation |\n"
        risks_md += "|------|----------|------------|\n"
        for r in proposal["risks"]:
            risks_md += f"| {r['risk']} | {r['severity']} | {r['mitigation']} |\n"
        risks_md += "\n"

    # Success metrics section
    metrics_md = ""
    if proposal["success_metrics"]:
        metrics_md = "### Success Metrics\n\n"
        metrics_md += "| Metric | Current | Target |\n"
        metrics_md += "|--------|---------|--------|\n"
        for m in proposal["success_metrics"]:
            current = m.get("current", "N/A")
            metrics_md += f"| {m['metric']} | {current} | {m['target']} |\n"
        metrics_md += "\n"

    # References section
    refs_md = ""
    if proposal.get("references"):
        refs_md = "### References\n\n"
        for ref in proposal["references"]:
            if ref.get("url"):
                refs_md += f"- [{ref.get('title', ref['url'])}]({ref['url']})\n"
            else:
                refs_md += f"- {ref.get('title', str(ref))}\n"

    body = f"""## Problem

{proposal['problem_description']}

{evidence_md}
## Proposed Solution

{proposal['solution_approach']}

{target_files_md}
{pseudo_code_md}{risks_md}{metrics_md}{refs_md}
---

## Metadata

| Field | Value |
|-------|-------|
| Proposed By | `{organism_id}` |
| Generation | {generation} |
| Genome Branch | `{genome_branch}` |
| Created At | {datetime.now(timezone.utc).isoformat()} |

---

> 🧬 This is an **Evolution Proposal** automatically created by an EvoAgent.
> It describes a potential improvement to the agent's genome (source code).
>
> **Next Steps:**
> 1. Review and discuss the proposal
> 2. If approved, a coding agent will implement the changes
> 3. Changes will be tested and merged to create a new generation
"""

    return body


async def create_github_issue(
    proposal: EvolutionProposal,
    organism_id: str,
    generation: int,
    genome_branch: str
) -> dict:
    """创建 GitHub Issue"""

    github_token = os.environ.get("GITHUB_TOKEN")
    github_repo = os.environ.get("GITHUB_REPO")

    if not github_token or not github_repo:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPO required")

    # Format issue
    title = f"[EVO-PROPOSAL] {proposal['title']}"
    body = format_proposal_as_markdown(
        proposal, organism_id, generation, genome_branch
    )

    # Labels
    labels = [
        "evolution-proposal",
        f"gen-{generation}",
        f"organism-{organism_id}"
    ]

    # Add risk-based label
    max_risk = "low"
    for r in proposal.get("risks", []):
        severity = r.get("severity", "low")
        if severity == "critical":
            max_risk = "critical"
            break
        elif severity == "high" and max_risk != "critical":
            max_risk = "high"
        elif severity == "medium" and max_risk not in ["critical", "high"]:
            max_risk = "medium"

    labels.append(f"risk-{max_risk}")

    # Use gh CLI to create issue (simpler than API)
    import subprocess

    loop = asyncio.get_event_loop()

    # First, try to create with labels
    cmd = [
        "gh", "issue", "create",
        "--repo", github_repo,
        "--title", title,
        "--body", body
    ]

    for label in labels:
        cmd.extend(["--label", label])

    logger.info(f"Creating GitHub issue: {title}")

    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "GH_TOKEN": github_token}
        )
    )

    # If labels failed, retry without labels
    if result.returncode != 0 and "label" in result.stderr.lower():
        logger.warning(f"Labels not found, retrying without labels: {result.stderr}")
        cmd = [
            "gh", "issue", "create",
            "--repo", github_repo,
            "--title", title,
            "--body", body
        ]
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env={**os.environ, "GH_TOKEN": github_token}
            )
        )
        labels = []  # Clear labels since we couldn't add them

    if result.returncode != 0:
        logger.error(f"gh CLI error: {result.stderr}")
        raise RuntimeError(f"Failed to create issue: {result.stderr}")

    # Parse issue URL from output
    issue_url = result.stdout.strip()
    issue_number = int(issue_url.split("/")[-1])

    logger.info(f"Created issue #{issue_number}: {issue_url}")

    return {
        "issue_number": issue_number,
        "issue_url": issue_url,
        "title": title,
        "labels": labels
    }


async def save_proposal_locally(
    proposal: EvolutionProposal,
    organism_id: str,
    generation: int
) -> str:
    """保存 Proposal 到本地（备份/离线使用）"""

    proposals_dir = Path("/workspace/.evo_proposals")
    proposals_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"proposal_{organism_id}_{generation}_{timestamp}.json"
    filepath = proposals_dir / filename

    proposal_data = {
        "metadata": {
            "organism_id": organism_id,
            "generation": generation,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "proposed"
        },
        "proposal": proposal
    }

    with open(filepath, "w") as f:
        json.dump(proposal_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved proposal locally: {filepath}")
    return str(filepath)


async def list_local_proposals() -> list[dict]:
    """列出本地保存的 Proposals"""

    proposals_dir = Path("/workspace/.evo_proposals")
    if not proposals_dir.exists():
        return []

    proposals = []
    for filepath in proposals_dir.glob("proposal_*.json"):
        with open(filepath) as f:
            data = json.load(f)
            data["local_path"] = str(filepath)
            proposals.append(data)

    return sorted(
        proposals,
        key=lambda x: x["metadata"]["created_at"],
        reverse=True
    )
