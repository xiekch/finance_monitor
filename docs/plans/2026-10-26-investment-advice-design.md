# 投资建议与复盘 — 设计文档

日期：2026-10-26

## 背景与目标

现有任务都从已抓取的行情或社媒帖子出发，再交给模型写简报。`morning_briefing` 的提示词虽然允许搜索，但现价和涨跌幅仍以抓取结果为准。

本设计新增一条独立链路：模型自己搜索资料，给出可事后对照的投资建议；之后按价格和逻辑复盘，把事件过程留在原文件里，并把可复用经验写进摘录。下一次给建议之前，模型必须读到未到期建议和这些复盘结果。

## 已确认的需求

- 不读取行情抓取结果，也不读取 X / 微博帖子。资料由模型在当次调用里自己搜索。
- 标的由模型选择，不限于 `config/monitor.py` 的监控池。
- 每天 1～3 条建议。每条必须有标的、方向、具体到期日、目标价、失效条件。到期日不超过创建日起 31 天。
- 方向只允许：看多、看空、观望。看多的目标价高于参考价，看空的目标价低于参考价。观望的目标价是等待触发的价位。
- 同一标的已有未到期建议时，不再发新建议。
- 两个职责、四条调度：一条发建议，三条做复盘。
- 复盘同时看价格和逻辑，并留下事件过程。
- 同一条建议可以复查多次。新内容只追加，不覆盖旧复盘。
- 三档复盘都要：
  - 每天结案「到期日早于今天且仍为 open」的建议。正常情况下就是昨天到期的；漏跑或失败留下的，下一次一并补结
  - 每周回溯上一自然周（周一至周日）发出的建议
  - 每月回溯上一自然月发出的建议
- 建议任务在调用模型前，读取未到期建议的摘要，以及 `lessons.md` 最近 30 条经验，放进提示词。
- 模型给建议前，可以自己搜索、读取已沉淀的全部建议、复盘结果和经验，不限于提示词里的摘要。
- 输出的建议文件和 `lessons.md` 都 commit 进本仓库并 push。
- 只在能联网搜索的后端上运行。当前只有 Cursor cloud agent 满足。

## 非目标

- 不把建议拆成关系表，不用 SQLite，也不引入 MongoDB。
- 不接入现有 `FetchAStock` / `FetchUSStock` / `FetchCrypto` / `FetchFutures` / `FetchXPosts` / `FetchWeiboPosts`。
- 不把这四条任务放进 `briefings` 或 `morning_pack`。
- 不做仓位管理和自动下单。
- 不把全部历史全文塞进每一次提示词。

## 架构

四条调度都不接抓取步骤。搜索发生在当前 LLM 调用里。项目现在的后端是 Cursor cloud agent（`config/social.py` 的 `_LLM_PROVIDER = "cursor"`）。实现时给 `CursorLLMClient` 增加一个直接接收完整提示词的 `complete(prompt)`，建议和复盘都走它，不复用简报的 `BriefingInput`。

投资任务的 agent 挂载本仓库：创建 agent 时带上 `repos: [{"url": ADVICE_REPO_URL, "startingRef": ADVICE_REPO_REF}]`，默认 `https://github.com/xiekch/finance_monitor` 和 `main`。这样模型能直接读仓库里的 `advice/`。现有简报仍创建无仓库 agent，不受影响。提示词要求 agent 只读，不修改、不提交仓库文件；写文件和提交都由本程序完成。

`build_investment_llm_client()` 在 provider 不是 `cursor` 时直接抛错。通义没有搜索工具，用它会让参考价和事件全靠模型编造，再照常落盘推送，所以不提供通义的 `complete`。正式实现前，先手动跑一次 `complete("搜索 NVDA 最新收盘价并给出来源链接")`，确认无仓库的 cloud agent 确实能联网。

```
investment_review_due      每天 08:20   到期日 < 今天 且 status=open
investment_advice          每天 09:00   读摘要 + 经验，写 1～3 条
investment_review_weekly   每周一 21:00 上一自然周发出的建议
investment_review_monthly  每月 1 日 21:10 上一自然月发出的建议
```

时间是北京时间，与 `config/schedule.py` 的其余 cron 一致。

结案放在到期日的次日早晨，是为了让到期日的 A 股收盘和美股收盘都已经发生。建议任务排在结案之后，当天的新建议能读到刚写下的结案和经验。

`build_tasks` 在启动时只构造一次 chain，之后每次调度都复用同一组 step 对象。所以「今天」必须在每次 `process()` 里取，不能在构造函数里算好存下。step 接收 `today_fn: Callable[[], date] = date.today`，测试注入固定函数。

周回溯、月回溯若同时写同一文件，存储层按文件路径加锁。后拿到锁的一方先重读，再判断有没有新发现。每条复盘单独调用模型，写完一条就保存。

每次复盘运行最多处理 `MAX_REVIEWS_PER_RUN = 20` 份文件，按 `expiry_date`、再按 `id` 升序取前 20 份。到期档超出的部分下次会自动补上；周档、月档超出的部分本次跳过，推送里注明跳过几份。

推送使用现有 `WeChatNotifier` 的默认企业微信 webhook，不新增环境变量。每条建议、每段复盘各发一条 `send_markdown`。markdown 的链接可以点开，单条超过 3500 字会被截断，按条发送可以避开截断。每条末尾附一行「模型生成，非投资建议」。

复合组 `investment` 展开为上述四个 task key。`briefings` 和 `morning_pack` 保持原成员。

## 文档

根目录是项目根下的 `advice/`，由 `config/investment.py` 基于 `Path(__file__)` 算出，不依赖当前工作目录。它不在 `.gitignore` 里，由 git 跟踪。一条建议一个文件，复盘追加在同一文件。按建议的 `created_at` 放入月份目录：

```
advice/lessons.md
advice/2026-10/2026-10-26-1.md
```

`id` 由程序生成，形如 `{created_at}-{序号}`。序号是同一天已有 `{created_at}-N` 文件的最大 N 加 1。

文首放筛选、回读和校验要用的字段。价格类字段一律是纯数字，由模型直接输出，程序不从正文里抠数字：

```yaml
---
id: 2026-10-26-1
created_at: 2026-10-26
expiry_date: 2026-11-09
status: open
symbol: NVDA
name: 英伟达
direction: 看多
currency: USD
reference_price: 140
reference_date: 2026-10-26
reference_url: https://example.com/nvda
target_price: 160
stop_price: 120
---
```

`status` 为 `open` 或 `closed`。`stop_price` 可选：失效条件里有明确价位时填写，否则省略。

正文固定五节，标题使用二级标题：理由、目标价、失效条件、参考价、观察条件。正文给人读，可以写区间、依据和来源说明；校验只看文首。

以下任一情况，该条不落盘：

- 缺必填字段，或任一节为空
- 方向不是看多、看空、观望
- 价格字段不是正数
- `reference_url` 不以 `http://` 或 `https://` 开头
- `reference_date` 晚于 `created_at`，或早于 `created_at` 3 天以上
- 到期日早于创建日，或晚于创建日加 31 天
- 看多：`target_price <= reference_price`，或 `stop_price` 存在且 `>= reference_price`
- 看空：`target_price >= reference_price`，或 `stop_price` 存在且 `<= reference_price`
- 同一 `symbol` 已有未到期建议，或同一批里重复出现

观望的 `target_price` 是等待触发的价位，可以高于也可以低于参考价。

复盘只追加在文件末尾：

```markdown
## 复盘 2026-11-10 到期结案
- 价格：建议时 140 美元，目标价 160 美元，结案时 151 美元（+7.9%）。窗口内未碰到目标价。来源 …
- 逻辑：当初的催化剂是否发生
- 事件过程：这一窗口里按时间发生了什么
- 经验：一句可复用的话；没有就写「无」
```

周回溯、月回溯使用同一四行，标题末尾分别是 `周回溯`、`月回溯`。价格行要写出参考价、目标价、复盘时价格，以及窗口内有没有碰到目标价或失效条件。

价格评估窗口是 `created_at` 至 `min(复盘日, expiry_date)`。已结案的建议再被周档、月档回溯时，到期之后的走势可以在事件过程里提一句，但不用来判断建议对错，也不据此写经验。

观望的复盘：价格行写窗口内是否触及 `target_price`，触及时写日期和触及后的走势。不按涨跌判断方向对错，经验写「这次等待是否值得」。

`lessons.md` 每条经验一块：

```markdown
## 2026-11-10 · NVDA · 2026-10-26-1 · 到期结案
一句经验
```

建议任务只把最近 30 块放进提示词。更早的经验仍留在文件里供人阅读。

## 读取边界

建议任务的提示词里固定放两样历史，保证模型至少看到这些：

- 未到期建议的一行摘要：`id`、标的、方向、到期日、目标价、理由的第一句、最近一次复盘的价格行和逻辑行（去掉 `- 价格：` / `- 逻辑：` 前缀，各截到 60 字）。没有复盘就写「尚无复盘」。`status=open` 且 `expiry_date >= 今天` 的建议算未到期。
- `lessons.md` 最近 30 条。

除此之外，模型可以在挂载的仓库里自己搜索、读取 `advice/` 下的任何文件：已结案的建议和复盘、更早的经验、同一标的的历史记录。提示词说明目录结构和文件格式，并要求：

- 准备对某个标的给建议前，先查它在 `advice/` 里的历史建议和复盘
- 先读 `advice/lessons.md`，不只看提示词里的最近 30 条
- 只读，不修改、不新建、不提交任何文件

提示词里明确：未到期摘要中的标的不要再发新建议。

复盘任务的提示词放本档文件的全文和已有复盘，避免把旧事实再写成新发现。模型同样可以读 `advice/` 的其他文件作参考，比如同一标的的其他建议。

档期按本地日期计算：

- 到期档：`expiry_date < 今天`，且 `status=open`
- 周档：`created_at` 落在上一自然周。以周一为一周的第一天。2026-10-26 是周一，上一周是 2026-10-19 至 2026-10-25，两端都包含
- 月档：`created_at` 落在上一个自然月。2026-11-01 对应 2026-10-01 至 2026-10-31，两端都包含

## 新发现

周回溯和月回溯里，新发现是指建议正文和已有复盘都没有写过的事实：价格路径改变了结论、催化剂兑现或落空、失效条件被触发、目标价被碰到，或出现相反证据。

没有这些时，模型只返回 `NO_NEW_FINDING`。存储层不改文件，通知层不推送。本档全部都是这个结果时，整次运行静默。

有新发现才追加一节。经验不是「无」时，再追加到 `lessons.md`。

到期结案不使用 `NO_NEW_FINDING`。每次都追加一节，并把 `status` 写成 `closed`。模型若在到期档返回 `NO_NEW_FINDING`，这条视为解析失败，不改文件，仍为 open，下一次到期档会再试。同一条建议同一天既到期又落在周档或月档时，两档都看：结案一定留下；另一档若看到结案里已经写过的事实，就不再追加。

## 提交

每次运行写完文件后，提交一次，只提交 `advice/` 下的改动：

- `git add -- advice/`，再 `git commit -m <message> -- advice/`。工作区里 `advice/` 以外的改动不会被带进提交
- 本次运行没有写任何文件时不提交
- 提交信息：
  - 建议：`advice: 2026-10-26 新增 2 条`
  - 复盘：`advice: 2026-10-26 到期结案 3 份`、`advice: 2026-10-26 周回溯 1 份`、`advice: 2026-11-01 月回溯 4 份`
- 每次提交后都必须 `git push origin HEAD`，不提供关闭开关。被拒绝时先 `git pull --rebase --autostash`，再推一次
- 提交或推送失败只记日志，并在推送末尾注明「提交失败」或「推送失败」。文件已经写好，不回滚；下一次提交会把这次的改动一起带上

提交放在通知之前。到期结案在 08:20 运行并推送后，09:00 的建议任务挂载 `main` 时就能读到。

## 运行与失败

任务链不从抓取开始。建议任务自己读存储、调用模型、写文件、提交，再把要推送的正文交给通知步骤。复盘任务对本档每份文件重复「加锁、重读、调用模型、追加、解锁」，全部处理完提交一次，再把本次实际写下的复盘交给通知步骤。

失败时：

- 模型失败或输出无法解析：这一条不落盘，同一次运行继续处理其余文件
- 建议任务一条合法建议都没有：不创建空文件，推一条失败说明
- 一批里部分合法：只保存合法的，推送里注明丢掉几条
- 周档、月档为 `NO_NEW_FINDING`：不改文件、不推送
- 到期档没有文件：不推送
- 到期档单条失败：保持 open，下一次到期档重试
- 写文件先写同目录临时文件，完成后再替换原文
- 有成功也有失败时，企微先发成功内容，最后一条附失败条数和跳过份数

## 验收

单测不调用真实模型和网络。用固定回复、临时目录和注入的 `today_fn`。

- 非法建议不落盘：包括价格方向不对、`stop_price` 在错误一侧、`reference_date` 过旧、标的与未到期建议重复
- 合法建议写入对应月份目录，文首数字字段和五节正文都在
- 建议提示词包含未到期摘要和最近 30 条经验，不包含更早全文；摘要里的复盘结论来自价格行和逻辑行，而不是复盘标题
- 建议提示词说明可以读 `advice/`，并要求只读
- 投资任务创建 agent 时带 `repos`；简报创建 agent 时仍不带
- 写了文件的运行恰好产生一次提交，提交里只有 `advice/` 下的文件；没写文件时不提交
- 提交失败不影响推送，推送末尾注明失败
- 到期结案追加一节，`status` 改为 `closed`，旧正文还在；没有到期建议时不推送
- 到期日早于昨天、仍为 open 的建议会被到期档补结
- 同一个 step 对象在 `today_fn` 返回值变化后，按新日期取档期
- `NO_NEW_FINDING` 不改文件、不推送；有新发现才追加；经验不是「无」才写入 `lessons.md`
- 同一文件被两档复盘先后写时，后写的一方能看到先写入的内容
- 模型失败或无法解析时不留下半截文件
- provider 不是 cursor 时 `build_investment_llm_client()` 抛错
- 四条 cron 为 08:20、09:00、周一 21:00、每月 1 日 21:10
- 四个 key 只出现在 `investment` 组，不在 `briefings` 和 `morning_pack`

## 文件

```
config/investment.py                 # 根目录、仓库地址、提示词、条数上限、经验条数、每次复盘上限
config/schedule.py                   # 四条 cron
tasks.py                             # 注册四个 task，新增 investment 组
models/advice.py                     # 文档解析、渲染、校验
storage/advice_store.py              # 月份目录、原子写、锁、档期、经验摘录
storage/advice_git.py                # 只提交 advice/，推送与重试
clients/llm_client/cursor.py         # complete(prompt)，可选 repos
clients/llm_client/factory.py        # build_investment_llm_client()，非 cursor 抛错，挂载仓库
steps/investment_parse.py            # 模型输出解析、提示词拼装
steps/investment_advice.py           # 读历史、生成、校验、落盘
steps/investment_review.py           # 三档复盘
steps/notify/investment.py           # 有正文才推送，逐条 send_markdown
tests/conftest.py                    # 建议样本 fixture
tests/test_advice_doc.py
tests/test_advice_store.py
tests/test_advice_git.py
tests/test_investment_parse.py
tests/test_investment_llm.py
tests/test_investment_steps.py
tests/test_investment_tasks.py
```
