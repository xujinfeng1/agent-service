"""核心 Agent 引擎 —— ReAct 循环 + tool calling"""
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

from openai import AsyncOpenAI

from src.config import config
from src.tools import registry
from src.memory import memory, Session

logger = logging.getLogger(__name__)


class Agent:
    """AI Agent 核心引擎"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.max_rounds = config.max_tool_rounds

    async def chat(
        self,
        session_id: str,
        user_message: str,
        system_prompt: str = "",
        stream: bool = False,
        model_override: str = None,
        think_mode: bool = False,
    ):
        """对话入口 - 支持普通和流式"""
        session = memory.get_or_create(session_id)

        # 设置 system prompt（仅首次）
        if system_prompt and not any(
            m["role"] == "system" for m in session.messages
        ):
            session.add_message("system", system_prompt)

        session.add_message("user", user_message)

        if stream:
            return self._stream_chat(session, model_override, think_mode)
        else:
            return await self._run_agent_loop(session, model_override, think_mode)

    async def _run_agent_loop(self, session: Session, model_override: str = None, think_mode: bool = False) -> Dict:
        """ReAct Agent 循环"""
        msgs = session.get_messages(config.max_history_tokens)
        last_user = next((m["content"] for m in reversed(session.messages) if m["role"] == "user"), "")
        tools = self._filter_tools(registry.get_openai_tools(), last_user)

        try:
            return await self._do_loop(session, msgs, tools, model_override, think_mode)
        except Exception as e:
            logger.error(f"Agent error: {e}")
            return {
                "session_id": session.session_id,
                "reply": f"抱歉，服务出错：{str(e)}",
                "tool_calls": [],
                "finished": False,
            }

    async def _do_loop(self, session: Session, msgs: List[Dict], tools: List[Dict], model_override: str = None, think_mode: bool = False) -> Dict:
        """实际执行 Agent 循环"""
        for _ in range(self.max_rounds):
            # 构建请求参数
            kwargs = {
                "model": model_override or self.model,
                "messages": msgs,
                "tools": tools if tools else None,
                "tool_choice": "auto" if tools else None,
            }
            if think_mode:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            else:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

            response = await self.client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            msg = choice.message

            # 提取 reasoning_content
            reasoning = getattr(msg, "reasoning_content", "") or ""

            # 没有 tool calls → 最终回复
            if not msg.tool_calls:
                content = msg.content or ""
                session.add_message("assistant", content)
                return {
                    "session_id": session.session_id,
                    "reply": content,
                    "reasoning": reasoning,
                    "tool_calls": [],
                    "finished": True,
                }

            # 处理 tool calls
            tool_results = []
            assistant_msg = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
            # thinking mode: reasoning_content must be passed back for tool-call rounds
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            msgs.append(assistant_msg)

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                logger.info(f"🔧 Tool call: {tool_name}({args})")
                result_str = await registry.execute(tool_name, args)
                tool_results.append({
                    "tool": tool_name,
                    "arguments": args,
                    "result": result_str,
                })

                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # 超过最大轮次
        session.add_message("assistant", "抱歉，任务过于复杂，已达到最大工具调用次数限制。")
        return {
            "session_id": session.session_id,
            "reply": "抱歉，任务过于复杂，已达到最大工具调用次数限制。",
            "tool_calls": [],
            "finished": False,
        }

    async def _stream_chat(self, session: Session, model_override: str = None, think_mode: bool = False) -> AsyncGenerator[str, None]:
        """流式对话"""
        msgs = session.get_messages(config.max_history_tokens)
        tools = self._filter_tools(registry.get_openai_tools(), session.messages[-1]["content"] if session.messages else "")

        for round_num in range(self.max_rounds):
            kwargs = {
                "model": model_override or self.model,
                "messages": msgs,
                "tools": tools if tools else None,
                "tool_choice": "auto" if tools else None,
                "stream": True,
            }
            if think_mode:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            else:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

            stream = await self.client.chat.completions.create(**kwargs)
            print(f"[DEBUG] Got stream object", flush=True)

            # 收集流式输出
            content_parts = []
            reasoning_parts = []
            tool_calls_data: Dict[int, Dict] = {}
            finish_reason = None

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue
                finish_reason = chunk.choices[0].finish_reason

                # 思维链（thinking mode）
                reasoning_delta = getattr(delta, "reasoning_content", "") or ""
                if reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    yield json.dumps({"type": "reasoning", "content": reasoning_delta}, ensure_ascii=False) + "\n"

                # 普通文本
                if delta.content:
                    content_parts.append(delta.content)
                    yield json.dumps({"type": "text", "content": delta.content}, ensure_ascii=False) + "\n"

                # tool calls
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {
                                "id": tc_delta.id or "",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc_delta.id:
                            tool_calls_data[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_data[idx]["function"]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_data[idx]["function"]["arguments"] += tc_delta.function.arguments

            # 处理 tool calls
            if tool_calls_data and finish_reason == "tool_calls":
                tool_calls_list = list(tool_calls_data.values())
                yield json.dumps({
                    "type": "tool_start",
                    "tools": [tc["function"]["name"] for tc in tool_calls_list],
                }, ensure_ascii=False) + "\n"

                # 构建 assistant message
                assistant_msg = {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": tc["function"],
                        }
                        for tc in tool_calls_list
                    ],
                }
                # thinking mode: reasoning_content must be passed back for tool-call rounds
                full_reasoning = "".join(reasoning_parts)
                if full_reasoning:
                    assistant_msg["reasoning_content"] = full_reasoning
                msgs.append(assistant_msg)

                for tc in tool_calls_list:
                    tool_name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    logger.info(f"🔧 Tool call(stream): {tool_name}({args})")
                    result_str = await registry.execute(tool_name, args)
                    yield json.dumps({
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": result_str,
                    }, ensure_ascii=False) + "\n"

                    msgs.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

                # 继续循环获取最终回复
                continue

            # 最终回复
            full_content = "".join(content_parts)
            if full_content:
                session.add_message("assistant", full_content)
            yield json.dumps({"type": "done", "content": full_content}, ensure_ascii=False) + "\n"
            return

        yield json.dumps({"type": "error", "content": "达到最大工具调用轮次"}, ensure_ascii=False) + "\n"

    def add_tool(self, tool):
        """动态注册工具"""
        registry.register_tool(tool)

    def _filter_tools(self, tools: List[Dict], user_msg: str) -> List[Dict]:
        """上下文优化：根据用户意图过滤工具，减少 token 消耗"""
        msg = user_msg.lower()
        always_include = {"get_current_time", "calculate"}
        filtered = [t for t in tools if t["function"]["name"] in always_include]

        # 关键词 → 工具组映射
        keyword_map = {
            "圈": ["create_segment", "list_segments", "analyze_segment"],
            "人群": ["create_segment", "list_segments", "analyze_segment", "query_data"],
            "选客": ["create_segment", "list_segments", "analyze_segment", "query_data"],
            "客": ["create_segment", "list_segments", "analyze_segment"],
            "活动": ["create_campaign", "list_campaigns", "get_campaign_report", "query_data"],
            "营销": ["create_campaign", "list_campaigns", "query_data"],
            "画布": ["create_campaign", "list_campaigns"],
            "触达": ["create_campaign", "list_campaigns"],
            "渠道": ["create_campaign"],
            "数据": ["query_data", "get_campaign_report", "generate_report"],
            "报告": ["generate_report", "query_data", "get_campaign_report"],
            "报表": ["generate_report", "query_data"],
            "复盘": ["get_campaign_report", "query_data"],
            "总览": ["query_data", "generate_report"],
            "分析": ["analyze_segment", "multi_perspective", "query_data"],
            "多角度": ["multi_perspective"],
            "视角": ["multi_perspective"],
            "计划": ["generate_plan"],
            "步骤": ["generate_plan"],
            "竞品": ["web_fetch"],
            "网页": ["web_fetch"],
            "抓取": ["web_fetch"],
            "定时": ["schedule_task", "list_scheduled_tasks"],
            "知识": [],  # KB tools are not agent tools
        }

        matched = set()
        for kw, tool_names in keyword_map.items():
            if kw in msg:
                matched.update(tool_names)

        if not matched:
            # 没有关键词匹配 → 返回核心工具（查询类 + 常用）
            matched = {"list_segments", "list_campaigns", "query_data", "create_segment",
                       "create_campaign", "get_campaign_report", "analyze_segment"}

        for t in tools:
            if t["function"]["name"] in matched:
                filtered.append(t)

        # cap at max_tools_per_request
        if len(filtered) > config.max_tools_per_request:
            filtered = filtered[:config.max_tools_per_request]

        return filtered


# 全局 Agent 实例
agent = Agent()
