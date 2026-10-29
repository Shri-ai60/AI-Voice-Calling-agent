from datetime import UTC, datetime
import json
import logging
from typing import Any, Dict, List, Optional
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._last_fail_time: float = 0.0

    async def get_client(self) -> Optional[aioredis.Redis]:
        if self._redis is not None:
            return self._redis

        import time
        now = time.time()
        if (now - self._last_fail_time) < 30.0:
            return None

        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=0.3,
                socket_timeout=0.3,
            )
            await self._redis.ping()
            return self._redis
        except Exception as e:
            logger.debug(f"Redis is offline/unreachable ({e}); falling back to local storage.")
            self._redis = None
            self._last_fail_time = now
            return None

    # -------------------------------------------------------------
    # 1. Active Call State Cache
    # -------------------------------------------------------------
    async def save_active_call_session(
        self,
        call_id: str,
        data: Dict[str, Any],
        ttl_seconds: int = 3600,
    ) -> bool:
        """
        Stores active call session state in Redis with a TTL.
        Adds call_id to active_calls:set for O(1) membership and rapid listing.
        """
        client = await self.get_client()
        if not client:
            return False

        try:
            key = f"call_session:{call_id}"
            payload = {
                **data,
                "call_id": call_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            await client.set(key, json.dumps(payload), ex=ttl_seconds)
            await client.sadd("active_calls:set", call_id)
            return True
        except Exception as e:
            logger.warning(f"Redis error saving session {call_id}: {e}")
            return False

    async def update_call_status(
        self,
        call_id: str,
        status: str,
        duration: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Updates the active call status in Redis.
        If terminal state, removes from active set and lowers TTL.
        """
        client = await self.get_client()
        if not client:
            return False

        try:
            key = f"call_session:{call_id}"
            raw = await client.get(key)
            data = json.loads(raw) if raw else {"call_id": call_id}

            data["status"] = status
            data["updated_at"] = datetime.now(UTC).isoformat()
            if duration is not None:
                data["duration"] = duration
            if extra:
                data.update(extra)

            terminal = status in ("completed", "failed", "busy", "no_answer", "cancelled")
            if terminal:
                # Remove from active set and set short 5-minute cooldown TTL
                await client.srem("active_calls:set", call_id)
                await client.set(key, json.dumps(data), ex=300)
            else:
                await client.set(key, json.dumps(data), ex=3600)
                await client.sadd("active_calls:set", call_id)

            return True
        except Exception as e:
            logger.warning(f"Redis error updating status for {call_id}: {e}")
            return False

    async def get_active_call_session(self, call_id: str) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        if not client:
            return None

        try:
            raw = await client.get(f"call_session:{call_id}")
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Redis error getting session {call_id}: {e}")
            return None

    async def list_active_calls(self) -> List[Dict[str, Any]]:
        """
        Returns all currently active calls stored in Redis.
        """
        client = await self.get_client()
        if not client:
            return []

        try:
            call_ids = await client.smembers("active_calls:set")
            if not call_ids:
                return []

            results = []
            for cid in call_ids:
                raw = await client.get(f"call_session:{cid}")
                if raw:
                    results.append(json.loads(raw))
                else:
                    # Clean up orphaned ID
                    await client.srem("active_calls:set", cid)
            return results
        except Exception as e:
            logger.warning(f"Redis error listing active calls: {e}")
            return []

    async def remove_active_call(self, call_id: str) -> bool:
        client = await self.get_client()
        if not client:
            return False

        try:
            await client.srem("active_calls:set", call_id)
            await client.delete(f"call_session:{call_id}")
            return True
        except Exception as e:
            logger.warning(f"Redis error removing active call {call_id}: {e}")
            return False

    # -------------------------------------------------------------
    # 2. Live Conversation Turn Buffering
    # -------------------------------------------------------------
    async def append_live_transcript_turn(
        self,
        call_id: str,
        speaker: str,
        text: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> bool:
        client = await self.get_client()
        if not client:
            return False

        try:
            turn = {
                "speaker": speaker,
                "text": text,
                "start_time": start_time,
                "end_time": end_time,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            key = f"live_transcript:{call_id}"
            await client.rpush(key, json.dumps(turn))
            await client.expire(key, 3600)  # 1 hour TTL
            return True
        except Exception as e:
            logger.warning(f"Redis error appending transcript turn for {call_id}: {e}")
            return False

    async def get_live_transcript_turns(self, call_id: str) -> List[Dict[str, Any]]:
        client = await self.get_client()
        if not client:
            return []

        try:
            raw_list = await client.lrange(f"live_transcript:{call_id}", 0, -1)
            return [json.loads(x) for x in raw_list]
        except Exception as e:
            logger.warning(f"Redis error getting live transcript for {call_id}: {e}")
            return []

    async def clear_live_transcript(self, call_id: str) -> bool:
        client = await self.get_client()
        if not client:
            return False
        try:
            await client.delete(f"live_transcript:{call_id}")
            return True
        except Exception:
            return False

    # -------------------------------------------------------------
    # 3. Telemetry Metrics & Counters
    # -------------------------------------------------------------
    async def record_call_event_metric(self, event_type: str) -> None:
        client = await self.get_client()
        if not client:
            return

        try:
            today_str = datetime.now(UTC).strftime("%Y-%m-%d")
            pipe = client.pipeline()
            pipe.incr("metrics:calls:total")
            pipe.incr(f"metrics:calls:today:{today_str}")
            pipe.incr(f"metrics:event:{event_type}")
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Redis metrics recording error: {e}")

    async def record_call_duration_metric(self, duration_seconds: float) -> None:
        client = await self.get_client()
        if not client:
            return

        try:
            pipe = client.pipeline()
            pipe.incrbyfloat("metrics:duration:total_seconds", float(duration_seconds))
            pipe.incr("metrics:duration:count")
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Redis duration metric error: {e}")

    # -------------------------------------------------------------
    # 4. Agent Concurrency / Rate Limiting
    # -------------------------------------------------------------
    async def acquire_concurrency_slot(self, agent_id: str, max_concurrent: int = 10) -> bool:
        client = await self.get_client()
        if not client:
            return True  # Fail open if Redis unavailable

        try:
            key = f"ratelimit:agent:{agent_id}:concurrent"
            current = await client.incr(key)
            if current == 1:
                await client.expire(key, 7200)

            if current > max_concurrent:
                await client.decr(key)
                return False
            return True
        except Exception as e:
            logger.warning(f"Redis rate limit error for agent {agent_id}: {e}")
            return True

    async def release_concurrency_slot(self, agent_id: str) -> None:
        client = await self.get_client()
        if not client:
            return

        try:
            key = f"ratelimit:agent:{agent_id}:concurrent"
            val = await client.decr(key)
            if val < 0:
                await client.set(key, 0)
        except Exception as e:
            logger.warning(f"Redis release slot error for agent {agent_id}: {e}")


redis_service = RedisService()
