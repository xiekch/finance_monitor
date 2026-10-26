# LLM 三方对比：deepseek-v4-flash / qwen3.5-flash / qwen3.6-plus

日期：2026-06-01

## 目的

在 X 简报场景下，对 DashScope 平台上三个候选模型做 A/B：

- **deepseek-v4-flash**（轻量 reasoning）
- **qwen3.5-flash**(thinking-flash)
- **qwen3.6-plus**（thinking-heavy）

输入完全相同、prompt 完全相同，对比耗时、token 用量、信息覆盖、文字风格，给出场景化推荐。

## 测试条件

- **输入**：`social_posts` 表里 50 条 `@elonmusk` 推文（同一份数据）
- **Prompt**：当前 `SOCIAL_CONFIG["prompt_template"]`（已经过多轮迭代：含 🤖 / 💰 / 💡 标签、强制 `### emoji 主题` 标题、按时间正序、要求 `[要点摘要](URL)` 包装链接、禁前言客套）
- **客户端**：`langchain_openai.ChatOpenAI`，走 DashScope OpenAI 兼容端点
- **参数**：`temperature=0.3`、`max_tokens=16384`、`timeout=180s`
- **测试代码**：见文末附录

> ⚠️ 之前一版评测（仅 deepseek vs qwen3.6-plus）的数据在 prompt 大改后已失效，本文档基于最新 prompt 重测。Prompt 演进过程见文末附录。

## 量化对比

| 维度 | deepseek-v4-flash | qwen3.5-flash | qwen3.6-plus |
|---|---|---|---|
| **耗时** | **28.6s（最快）** | 46.6s | 83.9s |
| **input tokens** | 8148 | 9513 | 9513 |
| **output tokens (total)** | 3228 | 6775 | 4597 |
| ↳ reasoning（thinking） | 2704（84%） | **5927（87%）** | 3975（86%） |
| ↳ 可见 answer tokens | ~524 | ~848 | ~622 |
| **最终 markdown 字符数** | 1106 | **1486（最多）** | 1084 |
| **主题分组** | 🤖 + 💰（**2 组**） | 🤖 + 💰 + 💡（**3 组**） | 🤖 + 💰 + 💡（3 组） |
| **覆盖事件数** | 8 | **12（最多）** | 8 |
| `### emoji 主题` 标题 | ✓ | ✓ | ✓ |
| 链接文本是要点摘要 | ✓ | ✓ | ✓ |
| 无前言客套 | ✓ | ✓ | ✓ |
| finish_reason | stop | stop | stop |

## 定性观察

### deepseek-v4-flash
- **速度领先**：28s 完成，相比 qwen3.6-plus 快近 3×
- **只产出 🤖 / 💰 两组**，没有 💡 组——可能模型对"其他有价值"门槛较高，或主动跳过非两大主题内容
- **文字偏简洁**：每条提要短、信息密度适中
- **reasoning 已大幅增长**：v1 prompt 时 reasoning 仅 521，v3 prompt 加了"必须有 ### 标题"等约束后 reasoning 涨到 2704（5×）——prompt 复杂度直接增加了 deepseek 的思考量

### qwen3.5-flash
- **信息覆盖最全**：12 个事件、3 个主题分组完整
- **耗时中等**：47s，比 deepseek 慢 18s 但事件数多 50%
- **写作风格清晰**：每组主旨概括到位，bullet 紧凑
- **意外发现**：之前用 `max_tokens=8192` 跑会被截断（reasoning 就用了 7700+），调到 16384 后正常

### qwen3.6-plus
- **最慢**：84s，4× 于 deepseek
- **文字最老练**：用词更编辑化（"反向传播"、"代际为单位实现十倍跃升"、"全员持股计划共享估值跃升红利"），主旨概括更专业
- **覆盖 8 个事件**：跟 deepseek 同量，但选取的 8 条侧重不同——qwen3.6 更看长期投资逻辑（特斯拉 IPO 复利、SpaceX 员工股权机制）
- **token 浪费严重**：4597 output 里 86% 是 thinking，可见输出只占 ~14%

## 结论与场景推荐

| 场景 | 推荐 | 理由 |
|---|---|---|
| **每日 X 简报（推荐默认）** | **`qwen3.5-flash`** | 信息覆盖最全（12 vs 8）+ 耗时可接受（47s）+ 3 组完整分类 |
| 联调 / dryrun 体验优先 | `deepseek-v4-flash` | 速度最快，覆盖也够用 |
| 周报 / 月报式深度浓缩 | `qwen3.6-plus` | 文字老练，叙述老到 |
| 成本极端敏感 | `deepseek-v4-flash` | thinking 占比相对最低，单次成本最低 |

**建议默认设为 `qwen3.5-flash`**——是 X 简报这种"每日 1-2 次、追求覆盖度"场景下三者中最均衡的选择。

`deepseek-v4-flash` 适合当备用 / fallback：万一 qwen 系列出问题，deepseek 速度快、覆盖也合格。

`qwen3.6-plus` 留作"周末深度回顾"等低频场景；日常用性价比偏低。

## 关于 thinking 内容

3 个模型的 thinking 原文**均未拿到**，原因：`langchain_openai.ChatOpenAI` 没把 DashScope 扩展字段 `reasoning_content` 透传到 `AIMessage.additional_kwargs`（OpenAI 官方 schema 没这个字段）。

但 token 用量证明 thinking 占比都很高：

| Model | reasoning_tokens | output_tokens | reasoning 占比 |
|---|---|---|---|
| deepseek-v4-flash | 2704 | 3228 | 84% |
| qwen3.5-flash | 5927 | 6775 | 87% |
| qwen3.6-plus | 3975 | 4597 | 86% |

要拿 thinking 原文需绕开 langchain，用 `openai` SDK 直连 + `extra_body={"enable_thinking": True}` 或流式读 `delta.reasoning_content`。当前业务无需 thinking 内容，未跟进。

## 三份完整输出

### deepseek-v4-flash 输出（1106 chars）

```markdown
### 🤖 AI 技术
Grok Build 快速迭代，Agent 能力增强；Terafab 规划万卡级 AI 芯片；特斯拉自动驾驶获用户信赖；Grok 应利用用户反馈优化内容生成。

- @yunta_tsai: [提出用子 Agent 自动迭代策略，定制系统提示优化 Grok 4.3 VLM 的评估任务](https://x.com/elonmusk/status/2060453492779606269)
- @XFreeze: [Grok Build v0.2.11 更新：新增命令、Agent 共享、多平台支持、上下文压缩、终端视频 30fps 等大量改进](https://x.com/elonmusk/status/2060605320729186601)
- @LaceyPresley: [Terafab 计划年产 1000 亿颗 AI 芯片，80% 为辐射硬化 D3 芯片用于轨道数据中心，20% 为 AI5/AI6 边缘推理](https://x.com/elonmusk/status/2060607186422714577)
- @unclebobmartin: [特斯拉 FSD 已超越人类驾驶，感知与反应速度更优，用户完全信任](https://x.com/elonmusk/status/2061221391937217011)
- @beffjezos: [Grok 应利用用户 engagement 反馈作为 RL 信号，优化帖子生成能力](https://x.com/elonmusk/status/2061268036208971886)

### 💰 投资机会
SpaceX Starlink 商业回报极高，特斯拉长期投资价值显著，SpaceX 员工股票期权创造巨额财富。

- @wintonARK: [Starlink on Starship 单次发射成本约 5 亿美元，年收入 12 亿，实现 13 倍现金回报](https://x.com/elonmusk/status/2060487070729048239)
- @JonErlichman: [特斯拉 IPO 投资 2600 美元如今价值超 100 万美元，彰显长期持有回报](https://x.com/elonmusk/status/2060913698147823751)
- @petersellis: [SpaceX 通过定期流动性和员工股票期权，使蓝领工人也能获得巨额财富，反映公司高估值](https://x.com/elonmusk/status/2061308444519571869)
```

### qwen3.5-flash 输出（1486 chars）

```markdown
### 🤖 AI 技术
本组汇总了 Grok 构建工具更新、VLM 提示工程技巧、大模型训练数据策略及自动驾驶技术进展。
- @yunta_tsai: [Grok 4.3 VLM 通过子代理迭代优化策略以提升召回率和精确度](https://x.com/elonmusk/status/2060453492779606269)
- @XFreeze: [Grok Build v0.2.11 新增终端支持、子代理共享后端及交互式文件读取功能](https://x.com/elonmusk/status/2060605320729186601)
- @beffjezos: [Grok 利用 X 平台受众互动反馈数据进行强化学习训练优势分析](https://x.com/elonmusk/status/2061268036208971886)
- @unclebobmartin: [特斯拉 Cybertruck 自动驾驶系统反应速度优于人类，信任度显著提升](https://x.com/elonmusk/status/2061221391937217011)
- @LaceyPresley: [Terafab 计划年产 1000 亿颗 AI 芯片，目标 1 太瓦算力覆盖太空与地面边缘计算](https://x.com/elonmusk/status/2060607186422714577)
- @yunta_tsai: [当前 AI 发展状态综述链接分享](https://x.com/elonmusk/status/2061310800015569089)

### 💰 投资机会
本组聚焦 Starlink 商业模式回报测算、SpaceX 员工股权财富效应及特斯拉历史投资回报数据。
- @wintonARK: [Starlink 单次发射成本约 5 亿美元，带宽年营收可达 12 亿美元，现金回报率高达 13 倍](https://x.com/elonmusk/status/2060487070729048239)
- @petersellis: [SpaceX 向所有员工（包括技工）发放股票期权，通过流动性机制创造显著财富效应](https://x.com/elonmusk/status/2061308444519571869)
- @JonErlichman: [特斯拉 IPO 早期投资者 2600 美元投入如今价值超百万美元的复利效应](https://x.com/elonmusk/status/2060913698147823751)

### 💡 其他有价值内容
本组包含 SpaceX 能源基础设施扩展、卫星部署运营进度及车辆安全验证数据。
- @DavidSHolz: [SpaceX 在轨太阳能功率从 Gen1 的 10MW 增至 Gen3 的 1000MW，每几年翻十倍](https://x.com/elonmusk/status/2060483139374358651)
- @SawyerMerritt: [2026 年 SpaceX 已完成第 50 次 Starlink 发射，累计部署 1375 颗卫星](https://x.com/elonmusk/status/2060968761402830885)
- @SawyerMerritt: [Model 3 坠崖事故中两名乘客仅受中度伤害，验证车辆结构安全性](https://x.com/elonmusk/status/2061268418750476762)
```

### qwen3.6-plus 输出（1084 chars）

```markdown
### 🤖 AI 技术
xAI 加速迭代 Grok Build 智能体开发环境，探索利用社交平台互动数据强化模型训练，并验证特斯拉 FSD 的战术驾驶可靠性。
- @elonmusk: [Grok Build 快速迭代至 v0.2.11，新增子智能体共享终端、上下文压缩优化及多平台支持，正从早期 CLI 向专业级 Agentic 编程环境演进](https://x.com/elonmusk/status/2060605320729186601)
- @elonmusk: [Grok 具备利用 X 平台海量用户互动与受众反馈数据进行强化学习（RL）的独特优势，有望成为生成高传播力内容的最佳 AI](https://x.com/elonmusk/status/2061268036208971886)
- @elonmusk: [特斯拉 FSD 战术驾驶能力已获资深开发者认可，其环境感知与反应速度超越人类，人类角色正转向更高层级的战略监督](https://x.com/elonmusk/status/2061221391937217011)

### 💰 投资机会
特斯拉与 SpaceX 的长期资本回报及员工股权激励模式凸显硬科技公司的估值潜力与财富分配效应。
- @elonmusk: [特斯拉 IPO 早期投资展现惊人长期复利，2600 美元初始投入当前价值已突破百万美元，印证硬科技长线持有逻辑](https://x.com/elonmusk/status/2060913698147823751)
- @elonmusk: [SpaceX 通过无双重触发条件的定期流动性机制与全员持股计划，使一线技术工人共享公司估值跃升红利，构建强绑定的人才激励模型](https://x.com/elonmusk/status/2061308444519571869)

### 💡 其他有价值内容
航天基础设施的能源部署呈指数级增长，同时行业对火箭研发中的非计划解体事件保持理性认知。
- @elonmusk: [SpaceX 星链卫星在轨太阳能部署规模正以代际为单位实现十倍跃升，从初代 10 兆瓦快速迈向三代的千兆瓦级空间能源网络](https://x.com/elonmusk/status/2060483139374358651)
- @elonmusk: [火箭研发中的"计划外快速拆解"（RUD）属航天工程常态，技术突破依赖于持续试错而非规避风险](https://x.com/elonmusk/status/2060454545960878475)
```

## 附录 A：Prompt 迭代历程

本次三方对比基于 prompt **v3**。v1/v2 期间发现的问题：

| 版本 | 关键改动 | 触发的问题 |
|---|---|---|
| v1 | 初版，含 `user_prompt_extra` 占位、4 条编号列表、"按时间倒序" | LLM 输出含 "好的，这是为您..." 客套；推文按账号分组而非时间序 |
| v2 | 合入 `user_prompt_extra`、`▫️→💡`、加客套约束、按时间正序、要求 `[显示文本](URL)` | "显示文本" 4 字被 LLM 当字面占位输出；deepseek-v4-flash 失去 `### 标题` 结构（直出 bullet）；qwen3.5-flash 被 `max_tokens=8192` 截断 |
| v3（当前） | 精简成 3 段；明确"每组用 `### emoji 主题名` 三级标题开头"；链接文本约束改为"必须是要点摘要"；`max_tokens` 调到 16384 | 三模型都跑出干净结构 |

## 附录 B：测试代码

```python
from dotenv import load_dotenv
load_dotenv("/Users/xie/code/finance_monitor/.env")

import os, sqlite3, time
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from models.social import SocialPost
from config.social import SOCIAL_CONFIG
from clients.llm_client import TongyiLLMClient, BriefingInput

conn = sqlite3.connect("market_data.db")
rows = conn.execute("""
    SELECT post_id, author, author_name, text, created_at, url, is_retweet, referenced_url
    FROM social_posts
""").fetchall()
conn.close()
posts = [SocialPost(post_id=r[0], author=r[1], author_name=r[2] or "", text=r[3],
                    created_at=r[4], url=r[5] or "", is_retweet=bool(r[6]),
                    referenced_url=r[7]) for r in rows]
bi = BriefingInput(posts=posts, window_hours=SOCIAL_CONFIG["window_hours"],
                   max_chars=SOCIAL_CONFIG["push_max_chars"])

template = SOCIAL_CONFIG["prompt_template"]
stub = TongyiLLMClient.__new__(TongyiLLMClient)
stub.prompt_template = template
prompt = stub._render_prompt(bi)

cfg = SOCIAL_CONFIG["llm_provider"]
for model in ["deepseek-v4-flash", "qwen3.5-flash", "qwen3.6-plus"]:
    print(f"\n{'#'*72}\n# MODEL: {model}\n{'#'*72}")
    llm = ChatOpenAI(
        api_key=os.getenv(cfg["api_key_env"]),
        base_url=cfg["base_url"],
        model=model,
        temperature=cfg.get("temperature", 0.3),
        max_tokens=cfg["max_tokens"],
        timeout=cfg["timeout_sec"],
    )
    t0 = time.time()
    resp = llm.invoke([HumanMessage(content=prompt)])
    elapsed = time.time() - t0
    usage = getattr(resp, "usage_metadata", None) or {}
    print(f"[stats] elapsed={elapsed:.1f}s usage={dict(usage)}")
    print(f"\n--- ANSWER ({len(resp.content)} chars) ---\n{resp.content}")
```
