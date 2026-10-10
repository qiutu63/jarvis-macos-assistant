from app.agent.core import Agent
from app.agent.memory import MemoryStore
from app.providers.base import Response
from app.providers.mock_provider import MockProvider
from app.tools.builtin import build_registry


def test_sqlite_memories_are_bounded_explicit_and_deletable(tmp_path):
    path = tmp_path / "private" / "memory.sqlite3"
    memory = MemoryStore(path, history_turns=2)
    memory.save_turn("one", "answer one")
    memory.save_turn("two", "answer two")
    memory.save_turn("three", "answer three")
    assert [turn[0]["content"] for turn in memory.load_short_term()] == ["two", "three"]
    assert path.stat().st_mode & 0o777 == 0o600
    fact_id = memory.save_fact("偏好中文回复")
    task_id = memory.save_task("旅行计划", "比较周末交通")
    assert memory.delete_fact(fact_id)
    assert memory.delete_task(task_id)
    assert memory.counts() == (2, 0, 0)
    memory.clear_short_term()
    assert memory.counts() == (0, 0, 0)


async def test_agent_restores_short_term_and_adds_explicit_memories(tmp_path):
    class InspectProvider(MockProvider):
        seen = None

        async def chat(self, messages, tools):
            self.seen = messages
            return Response(content="好的")

    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.save_turn("上次问题", "上次回复")
    store.save_fact("喜欢简洁回答")
    store.save_task("当前项目", "完成记忆模块")
    provider = InspectProvider()
    agent = Agent(provider, build_registry(), memory_store=store)
    assert len(agent.history) == 1
    await agent.run("继续")
    assert provider.seen[1]["role"] == "system"
    assert "喜欢简洁回答" in provider.seen[1]["content"]
    assert "完成记忆模块" in provider.seen[1]["content"]
    assert provider.seen[2:4] == [
        {"role": "user", "content": "上次问题"},
        {"role": "assistant", "content": "上次回复"},
    ]
    agent.reset()
    assert store.counts() == (0, 1, 1)
