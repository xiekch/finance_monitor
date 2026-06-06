"""X 推文 AI 简报相关配置。所有运行时参数集中在此，避免污染 settings.py。"""

import os

SOCIAL_CONFIG = {
    # 总开关：False 时 XBriefingProducer / AIBriefingConsumer 不实例化
    "enabled": True,

    # 简报 cron 时段（小时，逗号分隔）
    "cron_hours": "8,20",
    # 触发分钟，避开整点全网 API 高峰；保留 0~59 整数（apscheduler CronTrigger.minute 语义）
    "cron_minute": 7,
    # 每次简报覆盖的回看窗口（仅作为 LLM prompt 上下文，不限制 since_id 增量）
    "window_hours": 12,

    # 关注的 X 账号白名单（不带 @）
    # twitterapi.io free tier 限速 1 req / 5 sec（fetch_limit=40）
    # → 平均 ~16s/账号；当前 10 个账号一轮约 2-3 分钟（cron 触发不阻塞主流程）
    "whitelist": [
        # 大模型核心人物（CEO / 技术领袖，独家信号密度最高）
        "elonmusk",
        "sama",            # OpenAI CEO
        "karpathy",        # 前 OpenAI / Tesla，深度技术
        "DarioAmodei",     # Anthropic CEO
        "demishassabis",   # Google DeepMind CEO
        "gdb",             # Greg Brockman, OpenAI President
        "ylecun",          # Yann LeCun, Meta AI 首席科学家
        "OpenAI",          # OpenAI 官方

        # 投资视角
        "naval",           # Naval Ravikant

        # 科技媒体 / 记者（独家爆料）
        "theinformation",  # The Information 科技商业深度报道
        "EricNewcomer",    # Newcomer newsletter, AI / VC 独家
    ],
    # 单账号单次拉取上限
    "fetch_limit_per_user": 40,

    # X 数据源。clients/social_client.py 按 name 派发到对应 client 类。
    # - twitterapi_io: free tier 限速 1 req / 5 sec；fetch_limit_per_user 通过 cursor 翻页凑齐
    # - socialdata: 按次付费，~$0.0002/req
    "social_provider": {
        "name": "twitterapi_io",
        "api_key_env": "TWITTERAPI_IO_KEY",
        "base_url": "https://api.twitterapi.io",
        # 20s：原 10s 与服务端响应时间相近，timeout 后立即 retry 会形成"双发"触发 429
        "timeout_sec": 20,
        # 是否拉取 reply 推文。True 时一并抓 @某人 的回复（quote_tweet 不影响）
        "include_replies": False,
    },

    # LLM
    # 走 OpenAI 兼容协议调 DashScope；换 provider 时改 base_url + api_key_env + model
    "llm_provider": {
        "name": "tongyi",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "deepseek-v4-flash",
        "temperature": 0.3,
        # thinking 模型 reasoning_tokens 占大头（qwen3.5-flash 实测 7700+），
        # 给 16384 兜底，否则会截在 answer 半路
        "max_tokens": 16384,
        # deepseek-v4-flash 比 qwen 快，但仍给 180s 兜底以防 prompt 大时排队
        "timeout_sec": 180,
        # DashScope qwen3 系列 thinking 默认开启，占 80%+ output tokens。
        # 关掉省 token 和时间，但可能损失主题聚合质量（需评测）。
        # - None: 不传该字段（沿用模型默认）
        # - False: 显式关闭（仅 qwen3 系列生效；deepseek 等会忽略）
        # - True: 显式开启
        "enable_thinking": False,
    },

    # Prompt 主体
    "prompt_template": (
        "你是 AI 行业资讯编辑。下面是过去 {window_hours} 小时来自我关注账号的 X 推文（按时间正序）。"
        "请筛选最有信息量的内容（跳过纯营销、转推无评论、互动闲聊），"
        "按主题分组生成简报。**简报总共最多列 20 条推文**，优先保留独家信息、重大事件、关键数据。\n\n"
        "关注信号与分组标签：\n"
        "- 🤖 AI 技术：agent / multi-agent、模型发布、训练 / 推理、开源、benchmark\n"
        "- 💰 投资机会：融资、估值、IPO、AI 上市公司动向（NVDA / META / GOOGL / 国内标的）、政策、AI 加密赛道\n"
        "- 💡 其他有价值内容\n\n"
        "格式（请严格遵守每一条）：\n"
        "- 标题：每组用 `### emoji 主题名` 三级标题；emoji 严格三选一（🤖 / 💰 / 💡），禁止使用其他任何 emoji\n"
        "- 推文条目：用 `- @作者: 一句话摘要 [原文链接](URL)` 列具体推文\n"
        "  - `@作者`：填**推文的真实原作者**。若 text 以 `RT @某人:` 开头，原作者是 `@某人`（不是上方 `[...]` 标记的 timeline 拥有者）\n"
        "  - 摘要：用一句话提炼推文要点，保留关键数字 / 专有名词 / 主体动作；删除情绪、感叹、纯营销\n"
        "  - 链接：固定写成 markdown 格式 `[原文链接](URL)`，URL 必须包在 `()` 里，**禁止裸 URL**\n"
        "- 整体：Markdown，不超过 {max_chars} 字符；直接从第一组标题开始，不要前言、客套、结尾总结\n\n"
        "推文清单：\n{posts_block}"
    ),
    # 推送给企微的硬上限（4096 字节内安全冗余）
    "push_max_chars": 3000,
}


def assert_social_env_ready():
    """启动期 fail-fast：enabled=true 但缺关键 env 时立即报错。"""
    if not SOCIAL_CONFIG["enabled"]:
        return
    missing = []
    for prov_key in ("social_provider", "llm_provider"):
        env_name = SOCIAL_CONFIG[prov_key]["api_key_env"]
        if not os.getenv(env_name):
            missing.append(env_name)
    if missing:
        raise RuntimeError(
            f"SOCIAL_CONFIG.enabled=True 但以下环境变量缺失: {missing}；"
            f"请在 .env 中设置或将 enabled 设为 False。"
        )
    if not SOCIAL_CONFIG["whitelist"]:
        raise RuntimeError(
            "SOCIAL_CONFIG.whitelist 为空；空跑会浪费 LLM 配额，请至少配置 1 个账号。"
        )
