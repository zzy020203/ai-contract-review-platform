"""进度事件总线：工作流节点 → Redis pub/sub → SSE 网关推送前端。"""
import json

import redis

from app.core.config import settings

CHANNEL_PREFIX = "review:events:"


def _client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def channel(task_id: int | str) -> str:
    return f"{CHANNEL_PREFIX}{task_id}"


def publish(task_id: int | str, event: dict) -> None:
    """工作流节点上报进度事件。"""
    try:
        _client().publish(channel(task_id), json.dumps(event, ensure_ascii=False, default=str))
    except redis.RedisError:
        # Redis 不可用时静默降级：进度落库即可，不影响主流程
        pass


def subscribe(task_id: int | str):
    """SSE 端订阅指定任务的事件通道，返回 pubsub 对象（调用方负责 close）。"""
    pubsub = _client().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel(task_id))
    return pubsub
