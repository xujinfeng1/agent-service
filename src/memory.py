"""会话记忆管理"""
import time
from typing import Dict, List
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # system, user, assistant, tool
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class Session:
    session_id: str
    messages: List[Dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str, **kwargs):
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.messages.append(msg)
        self.last_active = time.time()

    def get_messages(self, max_tokens: int = 4000) -> List[Dict]:
        """返回消息列表，超过 max_tokens 自动截断早期消息"""
        # 中文约 1.5 chars/token，英文约 4 chars/token，取平均 2.5
        limit = max_tokens * 2.5
        result = []
        kept_chars = 0
        for msg in reversed(self.messages):
            size = len(msg.get("content", ""))
            if msg["role"] == "system":
                result.insert(0, msg)  # system message 始终保留
            elif kept_chars + size <= limit:
                result.insert(0, msg)
                kept_chars += size
            else:
                break  # 更早的消息丢弃
        return result


class MemoryManager:
    """会话管理器"""

    def __init__(self, ttl_seconds: int = 3600):
        self.sessions: Dict[str, Session] = {}
        self.ttl = ttl_seconds

    def get_or_create(self, session_id: str) -> Session:
        """获取或创建会话"""
        self._cleanup()
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id=session_id)
        return self.sessions[session_id]

    def delete(self, session_id: str):
        """删除会话"""
        self.sessions.pop(session_id, None)

    def list_sessions(self) -> List[Dict]:
        """列出所有会话"""
        self._cleanup()
        return [
            {
                "session_id": s.session_id,
                "message_count": len(s.messages),
                "created_at": s.created_at,
                "last_active": s.last_active,
            }
            for s in self.sessions.values()
        ]

    def clear(self):
        self.sessions.clear()

    def _cleanup(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            sid for sid, s in self.sessions.items()
            if now - s.last_active > self.ttl
        ]
        for sid in expired:
            del self.sessions[sid]


# 全局实例
memory = MemoryManager()
