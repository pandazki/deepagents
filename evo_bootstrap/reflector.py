#!/usr/bin/env python3
"""
EvoAgent Reflector

反思驱动的进化机制。
在 Agent idle 时触发，基于执行日志分析问题并可能生成 Proposal。
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TypedDict, NotRequired

import yaml

logger = logging.getLogger("evo_reflector")

LOGS_DIR = Path("/workspace/.evo_logs")
EXECUTION_LOG_FILE = LOGS_DIR / "execution_log.yaml"


class TaskRecord(TypedDict):
    """任务执行记录"""
    id: str
    timestamp: str
    duration_ms: int
    status: str  # success | failure | timeout
    task_summary: str
    error: NotRequired[dict]
    user_feedback: NotRequired[dict]


class ExecutionLog(TypedDict):
    """执行日志"""
    tasks: list[TaskRecord]
    errors: list[dict]
    performance: dict


def ensure_logs_dir():
    """确保日志目录存在"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_execution_log() -> ExecutionLog:
    """加载执行日志"""
    ensure_logs_dir()

    if EXECUTION_LOG_FILE.exists():
        with open(EXECUTION_LOG_FILE) as f:
            return yaml.safe_load(f) or _empty_log()
    return _empty_log()


def _empty_log() -> ExecutionLog:
    """空的执行日志"""
    return {
        "tasks": [],
        "errors": [],
        "performance": {
            "total_tasks": 0,
            "success_count": 0,
            "failure_count": 0,
            "avg_duration_ms": 0
        }
    }


def save_execution_log(log: ExecutionLog):
    """保存执行日志"""
    ensure_logs_dir()
    with open(EXECUTION_LOG_FILE, "w") as f:
        yaml.dump(log, f, default_flow_style=False, allow_unicode=True)


def record_task_execution(
    task_id: str,
    task_summary: str,
    duration_ms: int,
    status: str,
    error: dict | None = None,
    user_feedback: dict | None = None
):
    """记录任务执行"""
    log = load_execution_log()

    record: TaskRecord = {
        "id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "status": status,
        "task_summary": task_summary[:200]  # 截断长任务描述
    }

    if error:
        record["error"] = error
        # 更新错误统计
        error_type = error.get("type", "unknown")
        existing = next(
            (e for e in log["errors"] if e.get("type") == error_type),
            None
        )
        if existing:
            existing["count"] = existing.get("count", 0) + 1
            existing["last_seen"] = record["timestamp"]
        else:
            log["errors"].append({
                "type": error_type,
                "count": 1,
                "first_seen": record["timestamp"],
                "last_seen": record["timestamp"],
                "sample_message": error.get("message", "")[:200]
            })

    if user_feedback:
        record["user_feedback"] = user_feedback

    log["tasks"].append(record)

    # 更新性能统计
    perf = log["performance"]
    perf["total_tasks"] = perf.get("total_tasks", 0) + 1
    if status == "success":
        perf["success_count"] = perf.get("success_count", 0) + 1
    else:
        perf["failure_count"] = perf.get("failure_count", 0) + 1

    # 计算平均耗时（简单移动平均）
    total = perf["total_tasks"]
    old_avg = perf.get("avg_duration_ms", 0)
    perf["avg_duration_ms"] = int(old_avg + (duration_ms - old_avg) / total)

    # 只保留最近 100 条任务记录
    if len(log["tasks"]) > 100:
        log["tasks"] = log["tasks"][-100:]

    save_execution_log(log)
    logger.info(f"Recorded task {task_id}: {status} ({duration_ms}ms)")


def record_user_feedback(task_id: str, feedback_type: str, message: str):
    """记录用户反馈（单独调用）"""
    log = load_execution_log()

    # 找到对应的任务
    for task in reversed(log["tasks"]):
        if task["id"] == task_id:
            task["user_feedback"] = {
                "type": feedback_type,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            save_execution_log(log)
            logger.info(f"Recorded feedback for {task_id}: {feedback_type}")
            return

    logger.warning(f"Task {task_id} not found for feedback")


def extract_issues_for_reflection(
    lookback_hours: int = 24,
    min_occurrences: int = 2
) -> dict:
    """
    从执行日志中提取值得反思的问题

    Args:
        lookback_hours: 回看多少小时的日志
        min_occurrences: 问题至少出现几次才值得关注

    Returns:
        包含问题摘要的字典
    """
    log = load_execution_log()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # 过滤时间范围内的任务
    recent_tasks = [
        t for t in log["tasks"]
        if datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")) > cutoff
    ]

    if not recent_tasks:
        return {"has_issues": False, "reason": "No recent tasks to analyze"}

    # 统计
    total = len(recent_tasks)
    failures = [t for t in recent_tasks if t["status"] != "success"]
    negative_feedback = [
        t for t in recent_tasks
        if t.get("user_feedback", {}).get("type") == "negative"
    ]

    # 重复出现的错误
    recurring_errors = [
        e for e in log["errors"]
        if e.get("count", 0) >= min_occurrences
    ]

    # 性能问题（耗时超过平均值 3 倍）
    avg_duration = log["performance"].get("avg_duration_ms", 1000)
    slow_tasks = [
        t for t in recent_tasks
        if t["duration_ms"] > avg_duration * 3
    ]

    # 判断是否有值得反思的问题
    has_issues = (
        len(failures) > total * 0.1 or  # 失败率 > 10%
        len(negative_feedback) > 0 or   # 有负面反馈
        len(recurring_errors) > 0 or    # 有重复错误
        len(slow_tasks) > total * 0.2   # 慢任务 > 20%
    )

    return {
        "has_issues": has_issues,
        "summary": {
            "total_tasks": total,
            "failures": len(failures),
            "failure_rate": round(len(failures) / total * 100, 1) if total > 0 else 0,
            "negative_feedback_count": len(negative_feedback),
            "recurring_errors": recurring_errors,
            "slow_tasks_count": len(slow_tasks)
        },
        "details": {
            "failure_samples": [
                {
                    "task": f["task_summary"],
                    "error": f.get("error", {}).get("message", "Unknown")
                }
                for f in failures[:5]  # 最多 5 个样本
            ],
            "feedback_samples": [
                {
                    "task": f["task_summary"],
                    "feedback": f.get("user_feedback", {}).get("message", "")
                }
                for f in negative_feedback[:5]
            ],
            "slow_task_samples": [
                {
                    "task": s["task_summary"],
                    "duration_ms": s["duration_ms"]
                }
                for s in slow_tasks[:5]
            ]
        }
    }


def build_reflection_prompt(issues: dict) -> str:
    """构建反思的 prompt"""
    summary = issues["summary"]
    details = issues["details"]

    prompt = f"""你正在进行一次反思（Reflection），回顾最近的执行记录。

## 执行摘要

- 总任务数: {summary['total_tasks']}
- 失败数: {summary['failures']} ({summary['failure_rate']}%)
- 用户负反馈: {summary['negative_feedback_count']}
- 慢任务: {summary['slow_tasks_count']}

## 重复出现的错误

"""
    for err in summary.get("recurring_errors", []):
        prompt += f"- **{err['type']}** (出现 {err['count']} 次): {err.get('sample_message', '')}\n"

    if details.get("failure_samples"):
        prompt += "\n## 失败任务样本\n\n"
        for f in details["failure_samples"]:
            prompt += f"- 任务: {f['task']}\n  错误: {f['error']}\n\n"

    if details.get("feedback_samples"):
        prompt += "\n## 用户负反馈\n\n"
        for f in details["feedback_samples"]:
            prompt += f"- 任务: {f['task']}\n  反馈: {f['feedback']}\n\n"

    if details.get("slow_task_samples"):
        prompt += "\n## 慢任务\n\n"
        for s in details["slow_task_samples"]:
            prompt += f"- {s['task']} ({s['duration_ms']}ms)\n"

    prompt += """

## 你的任务

基于以上执行记录，判断是否有**值得改进**的问题。

### 判断标准

只有满足以下条件才应该提出改进：

1. **问题是重复出现的** - 单次偶发错误不需要改进
2. **问题有明确的根因** - 你能指出是代码的哪个部分导致的
3. **改进是可行的** - 在你的能力范围内可以改进
4. **改进有明显价值** - 能显著减少错误或提升性能

### 不应该提出改进的情况

- 用户输入错误导致的问题
- 外部依赖（网络、API）导致的偶发问题
- 已经是最优实现，没有改进空间
- 问题太模糊，无法定位根因

## 输出格式

如果有值得改进的问题，输出 JSON：
```json
{
  "should_propose": true,
  "reasoning": "为什么这个问题值得改进",
  "proposal": {
    "title": "改进标题",
    "problem_description": "问题描述",
    "evidence": [...],
    "solution_approach": "解决方案",
    "target_files": [...],
    "risks": [...],
    "success_metrics": [...]
  }
}
```

如果没有值得改进的问题，输出：
```json
{
  "should_propose": false,
  "reasoning": "为什么当前不需要改进"
}
```

请用 JSON 格式输出你的分析结果。
"""

    return prompt


def get_log_stats() -> dict:
    """获取日志统计信息（用于 /health 等）"""
    log = load_execution_log()
    return {
        "total_tasks": log["performance"].get("total_tasks", 0),
        "success_rate": round(
            log["performance"].get("success_count", 0) /
            max(log["performance"].get("total_tasks", 1), 1) * 100,
            1
        ),
        "avg_duration_ms": log["performance"].get("avg_duration_ms", 0),
        "error_types": len(log["errors"])
    }
