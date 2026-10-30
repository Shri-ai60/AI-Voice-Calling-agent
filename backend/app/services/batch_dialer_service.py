import asyncio
import logging
from datetime import UTC, datetime
from typing import Dict, List
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.call import Call

logger = logging.getLogger("batch_dialer")


class BatchDialerService:
    """
    Intelligent Outbound Queue & Concurrency Dispatcher.
    
    When an agent batch is submitted (whether 3 numbers or 100 numbers):
    1. Holds calls in an asynchronous FIFO queue per agent.
    2. Spawns and manages exactly `concurrency` parallel worker tasks.
    3. Each worker takes one call at a time, dials it via the carrier,
       monitors it until caller hangup/completion, applies a polite 2.0s
       SIP trunk clearing delay, and automatically takes the next queued number.
    4. Ensures zero channel overlap, zero carrier collision, and 100% completion
       across all submitted numbers.
    """

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._workers: Dict[str, List[asyncio.Task]] = {}
        self._lock = asyncio.Lock()
        self._dispatch_lock = asyncio.Lock()
        self._last_dispatch_time = 0.0

    def _get_queue(self, agent_id: str) -> asyncio.Queue:
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()
        return self._queues[agent_id]

    async def enqueue_batch(
        self,
        agent_id: str,
        call_ids: List[str],
        concurrency: int = 1,
    ) -> int:
        """
        Enqueues call IDs and adjusts the worker pool to match the specified concurrency.
        """
        concurrency = max(1, min(20, int(concurrency or 1)))
        queue = self._get_queue(agent_id)

        for cid in call_ids:
            await queue.put(cid)

        logger.info(
            f"[BatchDialer] Enqueued {len(call_ids)} calls for Agent '{agent_id}'. "
            f"Queue size: {queue.qsize()}, Target Concurrency: {concurrency}"
        )

        async with self._lock:
            current_workers = [t for t in self._workers.get(agent_id, []) if not t.done()]
            needed = concurrency - len(current_workers)

            if needed > 0:
                for i in range(needed):
                    w_idx = len(current_workers) + i + 1
                    t = asyncio.create_task(
                        self._worker_loop(agent_id, w_idx),
                        name=f"batch_worker_{agent_id}_{w_idx}",
                    )
                    current_workers.append(t)
                logger.info(f"[BatchDialer] Running {len(current_workers)} active workers for Agent '{agent_id}'")

            self._workers[agent_id] = current_workers

        return queue.qsize()

    async def _worker_loop(self, agent_id: str, worker_index: int):
        queue = self._get_queue(agent_id)
        logger.info(f"[BatchDialer] Worker #{worker_index} started for Agent '{agent_id}'")

        from app.services.call_service import call_service

        # Carrier trunk stagger delay on initial worker startup:
        # Prevents concurrent workers from hammering VoBiz / telecom trunk at the exact same millisecond
        if worker_index > 1:
            stagger_sec = (worker_index - 1) * 3.0
            logger.info(f"[BatchDialer] Worker #{worker_index} staggering initial dispatch by {stagger_sec}s for carrier trunk isolation...")
            await asyncio.sleep(stagger_sec)

        while True:
            try:
                # Wait for next call_id, idle timeout of 90s if queue stays empty
                try:
                    call_id = await asyncio.wait_for(queue.get(), timeout=90.0)
                except asyncio.TimeoutError:
                    if queue.empty():
                        logger.info(f"[BatchDialer] Worker #{worker_index} idle timeout reached (queue empty). Exiting.")
                        break
                    continue

                logger.info(f"[BatchDialer] Worker #{worker_index} handling Call {call_id}. Remaining in queue: {queue.qsize()}")

                # Step 1: Dispatch call out to carrier with rate-limit separation
                try:
                    import time
                    async with self._dispatch_lock:
                        now_m = time.monotonic()
                        elapsed = now_m - self._last_dispatch_time
                        if elapsed < 3.0:
                            wait_time = 3.0 - elapsed
                            logger.info(f"[BatchDialer] Spacing carrier dispatch: waiting {wait_time:.2f}s before dialing Call {call_id}...")
                            await asyncio.sleep(wait_time)
                        self._last_dispatch_time = time.monotonic()
                        call = await call_service.dispatch_existing_call(call_id)
                except Exception as dispatch_err:
                    logger.error(f"[BatchDialer] Error dispatching call {call_id}: {dispatch_err}", exc_info=True)
                    async with AsyncSessionLocal() as session:
                        err_c = await session.get(Call, call_id)
                        if err_c:
                            err_c.status = "failed"
                            err_c.ended_at = datetime.now(UTC)
                            await session.commit()
                    queue.task_done()
                    await asyncio.sleep(1.0)
                    continue

                if not call or call.status in ("failed", "busy", "no_answer", "cancelled"):
                    logger.warning(f"[BatchDialer] Call {call_id} dispatch could not initiate or failed immediately. Moving to next.")
                    queue.task_done()
                    await asyncio.sleep(1.0)
                    continue

                # Step 2: Monitor call lifecycle until terminal status
                poll_count = 0
                max_polls = 600  # 600 * 2s = 20 minutes safety cap per call
                while True:
                    await asyncio.sleep(2.0)
                    poll_count += 1

                    async with AsyncSessionLocal() as session:
                        stmt = select(Call).where(Call.id == call_id)
                        res = await session.execute(stmt)
                        current_call = res.scalar_one_or_none()

                    if not current_call:
                        break

                    # Terminal states
                    if current_call.status in ("completed", "failed", "busy", "no_answer", "hangup", "cancelled"):
                        logger.info(
                            f"[BatchDialer] Call {call_id} finished: status='{current_call.status}', "
                            f"duration={current_call.duration or 0}s"
                        )
                        break

                    # Ringing timeout safeguard (e.g. 75s of ringing with no answer)
                    if current_call.status in ("initiating", "ringing") and poll_count > 37:
                        logger.info(f"[BatchDialer] Call {call_id} timed out ringing after 75s without answer.")
                        async with AsyncSessionLocal() as session:
                            stmt = select(Call).where(Call.id == call_id)
                            res = await session.execute(stmt)
                            c_up = res.scalar_one_or_none()
                            if c_up and c_up.status in ("initiating", "ringing"):
                                c_up.status = "no_answer"
                                c_up.ended_at = datetime.now(UTC)
                                await session.commit()
                        break

                    if poll_count >= max_polls:
                        logger.warning(f"[BatchDialer] Call {call_id} reached 20-minute safety cap.")
                        break

                queue.task_done()

                # Step 3: Polite 2.0s delay between calls so carrier SIP channel resets
                logger.info(f"[BatchDialer] Worker #{worker_index} completed call {call_id}. Channel resting 2.0s before next call.")
                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                logger.info(f"[BatchDialer] Worker #{worker_index} for Agent '{agent_id}' cancelled.")
                break
            except Exception as err:
                logger.error(f"[BatchDialer] Worker #{worker_index} unexpected exception: {err}", exc_info=True)
                await asyncio.sleep(2.0)


batch_dialer_service = BatchDialerService()

