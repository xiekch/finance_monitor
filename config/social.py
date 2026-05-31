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
        # "karpathy",
        # "sama",
        # "AnthropicAI",
    ],
    # 单账号单次拉取上限
    "fetch_limit_per_user": 50,

    # X 数据源（默认 socialdata.tools，按最终选定服务再调整 base_url 与 client 实现）
    "social_provider": {
        "name": "socialdata",
        "api_key_env": "SOCIALDATA_API_KEY",
        "base_url": "https://api.socialdata.tools",
        "timeout_sec": 10,
    },

    # LLM
    "llm_provider": {
        "name": "tongyi",
        "api_key_env": "DASHSCOPE_API_KEY",
        "model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 2048,
        "timeout_sec": 60,
    },

    # Prompt 主体（占位，后续可按需精修）
    "prompt_template": (
        "你是一个 AI 行业资讯编辑。下面是过去 {window_hours} 小时内来自我关注的"
        "AI 圈作者的若干条 X 推文（已按时间倒序）。请：\n"
        "1) 跳过纯营销、转推无新增评论、互动闲聊；\n"
        "2) 把剩余有信息量的内容按主题分组（每组 1–3 条）；\n"
        "3) 每组用一句话概括主旨，再列原始作者 + 链接；\n"
        "4) 用 Markdown 输出，控制在 {max_chars} 字符以内。\n\n"
        "用户偏好：{user_prompt_extra}\n\n"
        "推文清单：\n{posts_block}"
    ),
    "user_prompt_extra": "我特别关注 agent / multi-agent / 训练效率",
    # 推送给企微的硬上限（4096 字节内安全冗余）
    "push_max_chars": 3500,
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
