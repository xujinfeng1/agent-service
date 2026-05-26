"""CDP 工具 —— 通过 HTTP 调用 CDP 服务"""
import json
import logging
from src.tools import registry, ToolParameter

logger = logging.getLogger("agent.cdp")

CDP_URL = "http://127.0.0.1:8103/api/cdp"

async def _cdp_get(path: str) -> dict:
    """调用 CDP 服务 GET"""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CDP_URL}/{path}")
        r.raise_for_status()
        return r.json()


async def _cdp_post(path: str, data: dict) -> dict:
    """调用 CDP 服务 POST"""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{CDP_URL}/{path}", json=data)
        r.raise_for_status()
        return r.json()


def _fmt(data) -> str:
    """格式化输出为 JSON 字符串"""
    return json.dumps(data, ensure_ascii=False, indent=2)


# ========== 数据查询 ==========

@registry.register(
    name="query_data",
    description="查询 CDP 平台数据，支持：总览(overview)、人群列表(segments)、活动列表(campaigns)、人群画像(profile:{id})、活动报告(report:{id})",
    parameters=[
        ToolParameter(name="query_type", type="string",
                      description="查询类型: overview / segments / campaigns / profile:人群ID / report:活动ID",
                      required=True),
    ],
)
async def query_data(query_type: str) -> str:
    try:
        if query_type == "overview":
            return _fmt(await _cdp_get("dashboard"))
        elif query_type == "segments":
            return _fmt(await _cdp_get("segments"))
        elif query_type == "campaigns":
            return _fmt(await _cdp_get("campaigns"))
        elif query_type.startswith("profile:"):
            seg_id = query_type.split(":", 1)[1]
            return _fmt(await _cdp_get(f"segments/{seg_id}/profile"))
        elif query_type.startswith("report:"):
            camp_id = query_type.split(":", 1)[1]
            return _fmt(await _cdp_get(f"campaigns/{camp_id}/report"))
        else:
            return json.dumps({"error": f"未知查询类型: {query_type}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ========== 人群管理 ==========

@registry.register(
    name="create_segment",
    description="创建人群包，根据条件圈选目标用户",
    parameters=[
        ToolParameter(name="name", type="string", description="人群包名称", required=True),
        ToolParameter(name="rules", type="string", description="圈选规则描述", required=True),
        ToolParameter(name="estimated_size", type="number", description="预估人群规模", required=False),
    ],
)
async def create_segment(name: str, rules: str, estimated_size: int = 0) -> str:
    try:
        result = await _cdp_post("segments", {"name": name, "rules": rules, "estimated_size": estimated_size})
        return _fmt(result)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="list_segments",
    description="列出所有已创建的人群包",
    parameters=[
        ToolParameter(name="status", type="string",
                      description="筛选状态: ready/calculating，不传列出全部",
                      required=False),
    ],
)
async def list_segments(status: str = "") -> str:
    try:
        params = f"?status={status}" if status else ""
        return _fmt(await _cdp_get(f"segments{params}"))
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="analyze_segment",
    description="分析人群包画像，查看人群特征分布",
    parameters=[
        ToolParameter(name="segment_id", type="string", description="人群包 ID", required=True),
    ],
)
async def analyze_segment(segment_id: str) -> str:
    try:
        return _fmt(await _cdp_get(f"segments/{segment_id}/profile"))
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ========== 营销活动 ==========

@registry.register(
    name="create_campaign",
    description="创建营销活动",
    parameters=[
        ToolParameter(name="name", type="string", description="活动名称", required=True),
        ToolParameter(name="segment_id", type="string", description="目标人群 ID", required=True),
        ToolParameter(name="channels", type="string", description="投放渠道，逗号分隔", required=True),
        ToolParameter(name="budget", type="number", description="预算（元）", required=False),
        ToolParameter(name="start_date", type="string", description="开始日期 YYYY-MM-DD", required=False),
    ],
)
async def create_campaign(name: str, segment_id: str, channels: str,
                          budget: int = 0, start_date: str = "") -> str:
    try:
        result = await _cdp_post("campaigns", {
            "name": name, "segment_id": segment_id,
            "channels": channels, "budget": budget, "start_date": start_date,
        })
        return _fmt(result)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="list_campaigns",
    description="列出所有营销活动",
    parameters=[
        ToolParameter(name="status", type="string",
                      description="筛选状态: running/draft，不传列出全部",
                      required=False),
    ],
)
async def list_campaigns(status: str = "") -> str:
    try:
        params = f"?status={status}" if status else ""
        return _fmt(await _cdp_get(f"campaigns{params}"))
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="get_campaign_report",
    description="获取营销活动效果报告",
    parameters=[
        ToolParameter(name="campaign_id", type="string", description="活动 ID", required=True),
    ],
)
async def get_campaign_report(campaign_id: str) -> str:
    try:
        return _fmt(await _cdp_get(f"campaigns/{campaign_id}/report"))
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ========== 高级工具 ==========

@registry.register(
    name="generate_report",
    description="生成数据报告，汇总平台关键指标",
    parameters=[
        ToolParameter(name="report_type", type="string",
                      description="报告类型: daily/weekly/monthly/overview",
                      required=False),
    ],
)
async def generate_report(report_type: str = "overview") -> str:
    try:
        overview = await _cdp_get("dashboard")
        return _fmt({
            "report_type": report_type,
            "generated_at": overview.get("overview", {}),
            "recent_segments": overview.get("recent_segments", [])[:3],
            "recent_campaigns": overview.get("recent_campaigns", [])[:3],
        })
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="generate_plan",
    description="生成营销执行计划，根据目标拆解为具体步骤",
    parameters=[
        ToolParameter(name="goal", type="string", description="营销目标描述", required=True),
        ToolParameter(name="segment_id", type="string", description="目标人群 ID", required=False),
    ],
)
async def generate_plan(goal: str, segment_id: str = "") -> str:
    """占位工具，实际由 LLM 在 system prompt 中引导生成"""
    return _fmt({"goal": goal, "segment_id": segment_id,
                 "note": "请根据目标拆解具体执行步骤"})
