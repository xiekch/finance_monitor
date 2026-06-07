"""公众号 AI 早报配置。与 social.py 的 X 简报完全独立。"""

import os
from dotenv import load_dotenv

load_dotenv()

WECHAT_MP_CONFIG = {
    'app_id': os.getenv('WECHAT_MP_APP_ID', ''),
    'app_secret': os.getenv('WECHAT_MP_APP_SECRET', ''),
    'thumb_media_id': os.getenv('WECHAT_MP_THUMB_MEDIA_ID', ''),
}

MORNING_BRIEFING_CONFIG = {
    "cron_hour": 9,
    "cron_minute": 35,
    # 回看窗口：覆盖前一天晚报到今天早上
    "window_hours": 24,
    # 公众号内容可以长一些
    "push_max_chars": 4000,

    "prompt_template": (
        "你是一位资深财经编辑，负责为微信公众号撰写每日 AI 早报。"
        "请根据以下两部分素材，生成一份专业、简洁、可读性强的早报。\n\n"
        "## 素材一：今日行情概览\n\n{market_block}\n\n"
        "## 素材二：过去 {window_hours} 小时的 AI / 科技资讯（按时间正序）\n\n{posts_block}\n\n"
        "## 输出要求（请严格遵守）\n\n"
        "1. 整体结构分两大板块，用二级标题 `##`：\n"
        "   - `## 📊 今日行情速览`：基于素材一，按市场分组（A 股、美股、加密货币、期货等），"
        "每个标的一行，格式 `标的名(代码) 收盘价 涨跌幅%`，涨用 📈 跌用 📉\n"
        "   - `## 🤖 AI 资讯精选`：基于素材二，严格筛选最有价值的内容（跳过纯营销、转发无评论、"
        "互动闲聊），按主题分组，每组用三级标题 `### 主题名`\n"
        "2. 资讯条目格式：`- @作者: 一句话摘要 [原文链接](URL)`\n"
        "   - 摘要提炼要点，保留关键数字/专有名词/主体动作\n"
        "   - 链接用 markdown 格式 `[原文链接](URL)`\n"
        "3. 数量硬限：资讯条目总数不超过 15 条，超过必须砍掉价值最低的\n"
        "4. 风格：面向公众号读者，专业但不晦涩；禁止客套、前言、结尾总结\n"
        "5. 总长度不超过 {max_chars} 字符\n"
        "6. 直接从第一个板块标题开始输出\n"
    ),
}
