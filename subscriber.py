"""
InsightLens — 网页变更订阅监控

定时抓取指定 URL，对比内容变化，触发回调通知。
支持内存和文件存储两种持久化方式。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

try:
    from .models import Subscription, SubscriptionEvent
except ImportError:
    from models import Subscription, SubscriptionEvent

logger = logging.getLogger(__name__)

# 默认存储路径
DEFAULT_STORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".insightlens_data",
    "subscriptions",
)


class Subscriber:
    """
    页面变更监控订阅管理器。

    用法:
        sub = Subscriber()
        # 注册监控
        sid = await sub.subscribe("https://example.com", interval_minutes=30)
        # 手动检查变更
        events = await sub.check(sid)
        # 取消监控
        await sub.unsubscribe(sid)
        # 启动后台检查循环
        await sub.start_monitor_loop(callback=my_webhook_handler)
    """

    def __init__(self, store_dir: Optional[str] = None):
        self.store_dir = store_dir or DEFAULT_STORE_DIR
        os.makedirs(self.store_dir, exist_ok=True)
        self._subscriptions: Dict[str, Subscription] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        self._load_subscriptions()

    # ---- 订阅管理 ----

    async def subscribe(
        self,
        url: str,
        interval_minutes: int = 60,
        callback_url: Optional[str] = None,
    ) -> str:
        """
        订阅一个 URL 的变更监控。

        首次订阅会立即抓取一次内容作为基准。

        Args:
            url: 目标 URL
            interval_minutes: 检查间隔（分钟），最少 5 分钟
            callback_url: 变更时的回调 HTTP URL

        Returns:
            订阅 ID
        """
        import uuid
        interval_minutes = max(5, interval_minutes)

        # 检查是否已订阅相同 URL
        for sid, sub in self._subscriptions.items():
            if sub.url == url and sub.active:
                logger.info(f"URL already subscribed: {url} (sid={sid})")
                # 更新间隔
                sub.interval_minutes = interval_minutes
                self._save_subscriptions()
                return sid

        sub_id = str(uuid.uuid4())[:8]

        # 首次抓取
        content_hash = await self._fetch_hash(url)
        now = _now_iso()

        subscription = Subscription(
            id=sub_id,
            url=url,
            interval_minutes=interval_minutes,
            last_fetched_at=now,
            last_content_hash=content_hash,
            created_at=now,
            callback_url=callback_url or "",
            active=True,
        )

        self._subscriptions[sub_id] = subscription
        self._save_subscriptions()

        logger.info(f"Subscribed to {url} (sid={sub_id}, interval={interval_minutes}min)")
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """取消订阅"""
        if subscription_id in self._subscriptions:
            self._subscriptions[subscription_id].active = False
            self._save_subscriptions()
            logger.info(f"Unsubscribed: {subscription_id}")
            return True
        return False

    def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """获取订阅信息"""
        sub = self._subscriptions.get(subscription_id)
        if sub and sub.active:
            return sub
        return None

    def list_subscriptions(self) -> List[Subscription]:
        """列出所有活跃订阅"""
        return [s for s in self._subscriptions.values() if s.active]

    # ---- 变更检查 ----

    async def check(self, subscription_id: str) -> List[SubscriptionEvent]:
        """
        检查单个订阅的变更。

        对比当前内容 hash 与上次记录的 hash。

        Args:
            subscription_id: 订阅 ID

        Returns:
            变更事件列表（如果没有变化则为空）
        """
        sub = self.get_subscription(subscription_id)
        if not sub:
            logger.warning(f"Subscription not found: {subscription_id}")
            return []

        events: List[SubscriptionEvent] = []

        current_hash = await self._fetch_hash(sub.url)
        if current_hash is None:
            logger.warning(f"Failed to fetch {sub.url} for change detection")
            return events

        if sub.last_content_hash and current_hash != sub.last_content_hash:
            # 内容已变更
            change_summary = self._compute_change_summary(
                sub.last_content_hash, current_hash
            )
            event = SubscriptionEvent(
                subscription_id=subscription_id,
                url=sub.url,
                changed_at=_now_iso(),
                change_summary=change_summary,
                previous_hash=sub.last_content_hash,
                current_hash=current_hash,
            )
            events.append(event)

            # 触发回调
            if sub.callback_url:
                await self._trigger_callback(sub.callback_url, event)

        # 更新记录
        sub.last_content_hash = current_hash
        sub.last_fetched_at = _now_iso()
        self._save_subscriptions()

        return events

    async def check_all(self) -> Dict[str, List[SubscriptionEvent]]:
        """检查所有到期订阅的变更"""
        all_events: Dict[str, List[SubscriptionEvent]] = {}
        now = time.time()

        for sub in self.list_subscriptions():
            # 检查是否到检查间隔
            try:
                last_fetch = datetime.fromisoformat(sub.last_fetched_at).timestamp()
            except (ValueError, TypeError):
                last_fetch = 0

            elapsed_minutes = (now - last_fetch) / 60
            if elapsed_minutes >= sub.interval_minutes:
                events = await self.check(sub.id)
                if events:
                    all_events[sub.id] = events

        return all_events

    # ---- 后台监控循环 ----

    async def start_monitor_loop(
        self,
        callback: Optional[Callable[[Dict[str, List[SubscriptionEvent]]], None]] = None,
    ) -> None:
        """
        启动后台监控循环。

        Args:
            callback: 变更时的回调函数，接收 {sub_id: [events]} 字典
        """
        if self._running:
            logger.warning("Monitor loop already running")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(callback)
        )
        logger.info("Monitor loop started")

    async def stop_monitor_loop(self) -> None:
        """停止后台监控循环"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
        logger.info("Monitor loop stopped")

    async def _monitor_loop(
        self,
        callback: Optional[Callable[[Dict[str, List[SubscriptionEvent]]], None]] = None,
    ) -> None:
        """后台循环 - 每 60 秒检查一次"""
        while self._running:
            try:
                events = await self.check_all()
                if events and callback:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(events)
                        else:
                            callback(events)
                    except Exception as e:
                        logger.error(f"Monitor callback failed: {e}")
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            await asyncio.sleep(60)

    # ---- 内部方法 ----

    async def _fetch_hash(self, url: str) -> Optional[str]:
        """获取 URL 内容的 hash 值"""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx required for subscription fetch")
            return None

        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                verify=False,
            ) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    },
                )
                if resp.status_code == 200:
                    # 对响应内容做 hash（保留结构，忽略动态内容差异）
                    content = resp.text
                    # 去掉可能的动态 token/时间戳等
                    import re
                    content = re.sub(
                        r'(csrf[-_]?token|nonce|timestamp|_t)=["\']?\w+["\']?',
                        '',
                        content,
                        flags=re.I,
                    )
                    return hashlib.sha256(content.encode()).hexdigest()[:16]
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")

        return None

    async def _trigger_callback(self, url: str, event: SubscriptionEvent) -> None:
        """触发变更回调"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    url,
                    json=event.to_dict(),
                    headers={"Content-Type": "application/json"},
                )
                logger.info(f"Callback triggered: {url}")
        except Exception as e:
            logger.warning(f"Callback failed: {e}")

    @staticmethod
    def _compute_change_summary(old_hash: str, new_hash: str) -> str:
        """生成变更摘要"""
        return f"Content changed (hash: {old_hash[:8]} → {new_hash[:8]})"

    # ---- 持久化 ----

    def _subscriptions_path(self) -> str:
        return os.path.join(self.store_dir, "subscriptions.json")

    def _save_subscriptions(self) -> None:
        """保存订阅到 JSON 文件"""
        path = self._subscriptions_path()
        try:
            data = {
                sid: sub.to_dict()
                for sid, sub in self._subscriptions.items()
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save subscriptions: {e}")

    def _load_subscriptions(self) -> None:
        """从 JSON 文件加载订阅"""
        path = self._subscriptions_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, item in data.items():
                self._subscriptions[sid] = Subscription(**item)
            logger.info(f"Loaded {len(self._subscriptions)} subscriptions")
        except Exception as e:
            logger.warning(f"Failed to load subscriptions: {e}")


def _now_iso() -> str:
    """当前时间的 ISO 格式字符串"""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ===================== 测试 =====================
if __name__ == "__main__":
    async def test():
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Subscriber(store_dir=tmpdir)
            sid = await sub.subscribe("https://example.com", interval_minutes=5)
            print(f"✅ 订阅ID: {sid}")
            print(f"📋 活跃订阅: {len(sub.list_subscriptions())}")
            events = await sub.check(sid)
            print(f"🔍 检查变更: {len(events)} 个事件")
            ok = await sub.unsubscribe(sid)
            print(f"❌ 取消订阅: {ok}")
            print(f"📋 剩余订阅: {len(sub.list_subscriptions())}")

    asyncio.run(test())
