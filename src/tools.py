"""工具系统 —— 可插拔的工具注册与调用"""
import json
import inspect
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ToolParameter:
    name: str
    type: str  # string, number, boolean, object, array
    description: str
    required: bool = True
    enum: Optional[List[str]] = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: List[ToolParameter]
    func: Callable
    # 是否需要在执行后告诉 LLM 结果
    return_direct: bool = False

    def to_openai_schema(self) -> Dict:
        """转为 OpenAI function calling 格式"""
        properties = {}
        required = []
        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: List[ToolParameter],
        return_direct: bool = False,
    ):
        """装饰器方式注册工具"""

        def decorator(func: Callable):
            tool = Tool(
                name=name,
                description=description,
                parameters=parameters,
                func=func,
                return_direct=return_direct,
            )
            self._tools[name] = tool
            return func

        return decorator

    def register_tool(self, tool: Tool):
        """直接注册 Tool 对象"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict]:
        """列出所有工具信息"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": [
                    {"name": p.name, "type": p.type, "description": p.description,
                     "required": p.required}
                    for p in t.parameters
                ],
            }
            for t in self._tools.values()
        ]

    def get_openai_tools(self) -> List[Dict]:
        """获取所有工具的 OpenAI schema"""
        return [t.to_openai_schema() for t in self._tools.values()]

    async def execute(self, name: str, arguments: Dict) -> str:
        """执行工具并返回结果"""
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"error": f"Tool '{name}' not found"})

        try:
            # 检查函数是否是 async
            if inspect.iscoroutinefunction(tool.func):
                result = await tool.func(**arguments)
            else:
                result = tool.func(**arguments)
            # 确保返回字符串
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)


# 全局工具注册中心
registry = ToolRegistry()
