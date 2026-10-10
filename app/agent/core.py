import asyncio
import json
from collections import deque

from app.agent.executor import Executor
from app.agent.memory import MemoryStore
from app.agent.planner import Planner, SYSTEM_PROMPT
from app.agent.state import State
from app.events.bus import Event, EventBus
from app.providers.base import LLMProvider
from app.tools.registry import ToolRegistry


class Agent:
    def __init__(self, provider: LLMProvider, registry: ToolRegistry, *, max_steps: int = 6,
                 history_turns: int = 8, bus: EventBus | None = None, executor: Executor | None = None,
                 memory_store: MemoryStore | None = None):
        if not 1 <= max_steps <= 20 or not 1 <= history_turns <= 50:
            raise ValueError("无效的 Agent 循环或历史预算")
        self.planner = Planner(provider, registry)
        self.executor = executor or Executor(registry)
        self.bus = bus or EventBus()
        self.max_steps = max_steps
        self.memory_store = memory_store
        saved_history = memory_store.load_short_term() if memory_store else []
        self.history: deque[list[dict]] = deque(saved_history, maxlen=history_turns)
        self.state = State.WAITING
        self._lock = asyncio.Lock()

    def transition(self, state: State, event: str, detail: str = "") -> None:
        self.state = state
        self.bus.emit(Event(event, state.value, detail))

    def reset(self) -> None:
        self.history.clear()
        if self.memory_store:
            self.memory_store.clear_short_term()
        self.transition(State.WAITING, "agent.reset")

    async def run(self, text: str) -> str:
        if not text.strip() or len(text) > 16000:
            raise ValueError("请输入 1–16000 个字符")
        async with self._lock:
            self.transition(State.THINKING, "agent.started")
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            if self.memory_store:
                context = self.memory_store.prompt_context()
                if context:
                    messages.append({"role": "system", "content": context})
            for turn in self.history:
                messages.extend(turn)
            start = len(messages)
            messages.append({"role": "user", "content": text})
            try:
                for step in range(self.max_steps):
                    self.transition(State.PLANNING, "agent.thinking", f"决策 {step + 1}/{self.max_steps}")
                    response = await self.planner.next_step(messages)
                    if len(response.tool_calls) > 8:
                        raise RuntimeError("单轮工具调用超出上限")
                    messages.append(response.message())
                    if not response.tool_calls:
                        if not response.content.strip():
                            raise RuntimeError("模型返回空响应")
                        self.history.append(messages[start:])
                        if self.memory_store:
                            self.memory_store.save_turn(text, response.content)
                        self.transition(State.COMPLETED, "agent.completed")
                        return response.content
                    for call in response.tool_calls:
                        self.transition(State.EXECUTING, "agent.tool_called", call.name)
                        result = await self.executor.execute(call)
                        self.transition(State.OBSERVING, "agent.tool_result", "成功" if result["ok"] else result["error"])
                        messages.append({"role": "tool", "tool_call_id": call.id,
                                         "content": json.dumps(result, ensure_ascii=False)})
                raise RuntimeError("达到任务步数上限，已停止；请缩小任务范围后重试")
            except asyncio.CancelledError:
                self.transition(State.WAITING, "agent.cancelled")
                raise
            except Exception:
                # Failed partial transcripts never contaminate the next turn.
                self.transition(State.ERROR, "agent.error")
                raise
