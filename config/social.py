"""X 推文 AI 简报相关配置。所有运行时参数集中在此，避免污染 settings.py。"""

import os

SOCIAL_CONFIG = {
    # 总开关：False 时 XBriefingProducer / AIBriefingConsumer 不实例化
    "enabled": True,

    # 简报 cron 时段（小时，逗号分隔）
    "cron_hours": "8,20",
    # 每次简报覆盖的回看窗口（仅作为 LLM prompt 上下文，不限制 since_id 增量）
    "window_hours": 12,

    # 关注的 X 账号白名单（不带 @）
    "whitelist": [
        "elonmusk",
        # "karpathy",
        # "sama",
        # "AnthropicAI",
    ],
    # 单账号单次拉取上限
    "fetch_limit_per_user": 50,

    # X 数据源。clients/social_client.py 按 name 派发到对应 client 类。
    # - twitterapi_io: free tier 限速 1 req / 5 sec；fetch_limit_per_user 通过 cursor 翻页凑齐
    # - socialdata: 按次付费，~$0.0002/req
    "social_provider": {
        "name": "twitterapi_io",
        "api_key_env": "TWITTERAPI_IO_KEY",
        "base_url": "https://api.twitterapi.io",
        "timeout_sec": 10,
        # 是否拉取 reply 推文。True 时一并抓 @某人 的回复（quote_tweet 不影响）
        "include_replies": False,
    },

    # LLM
    # 走 OpenAI 兼容协议调 DashScope；换 provider 时改 base_url + api_key_env + model
    "llm_provider": {
        "name": "tongyi",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.6-plus",
        "temperature": 0.3,
        "max_tokens": 8192,
        # qwen3.6-plus 是 thinking 模型，处理 50 条推文 + 大 max_tokens 经常 60s+；给 180s 兜底
        "timeout_sec": 180,
    },

    # Prompt 主体
    "prompt_template": (
        "你是一个 AI 行业资讯编辑。下面是过去 {window_hours} 小时内来自我关注的"
        " AI 圈作者的若干条 X 推文（已按时间正序，旧 → 新）。\n\n"
        "重点关注两类信号：\n"
        "- AI 技术进展：agent / multi-agent、模型发布、训练 / 推理优化、开源新模型、benchmark 突破\n"
        "- 投资机会：融资轮次、估值变化、IPO 动向、AI 相关上市公司（NVDA / META / GOOGL / 国内 AI 标的）动作、政策监管、AI 加密赛道（agent token / DePIN）\n"
        "两类信号优先级 > 普通行业八卦；如某条强相关，可单独成组。\n\n"
        "请：\n"
        "1) 跳过纯营销、转推无新增评论、互动闲聊；\n"
        "2) 把剩余有信息量的内容按主题分组（每组 1–3 条）；如属投资机会用 💰 开头，技术进展用 🤖 开头，其他用 ▫️；\n"
        "3) 每组用一句话概括主旨，再列原作者 + 链接；链接必须用 Markdown 语法 `[显示文本](URL)` 包装；\n"
        "4) 用 Markdown 输出，控制在 {max_chars} 字符以内。\n\n"
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
