"""Task 调度配置。

与 TASK_REGISTRY 的 key 对应；value 描述触发器类型与参数。
- type: 'cron' | 'interval'，对应 APScheduler 的 CronTrigger / IntervalTrigger
- kwargs: 传给对应 trigger 构造函数的参数
所有时间为本机时区（一般是北京时间）。
"""

TASK_SCHEDULE = {
    # A 股
    'astock_minute': {
        'type': 'cron',
        'kwargs': {'hour': '9-14', 'minute': '*/5', 'day_of_week': 'mon-fri'},
    },
    'astock_daily': {
        'type': 'cron',
        'kwargs': {'hour': 15, 'minute': 30, 'day_of_week': 'mon-fri'},
    },
    'astock_weekly': {
        'type': 'cron',
        'kwargs': {'day_of_week': 'sat', 'hour': 8, 'minute': 0},
    },
    # 美股
    'usstock_minute': {
        'type': 'cron',
        'kwargs': {'hour': '21-23,0-4', 'minute': '*/5', 'day_of_week': 'mon-fri'},
    },
    'usstock_daily': {
        'type': 'cron',
        'kwargs': {'hour': 5, 'minute': 0, 'second': 0, 'day_of_week': 'mon-fri'},
    },
    'usstock_weekly': {
        'type': 'cron',
        'kwargs': {'day_of_week': 'mon', 'hour': 6, 'minute': 0, 'second': 0},
    },
    # 加密货币（24/7 市场）
    'crypto_minute': {
        'type': 'cron',
        'kwargs': {'minute': '*/5'},
    },
    'crypto_daily': {
        'type': 'cron',
        'kwargs': {'hour': 5, 'minute': 0, 'second': 0},
    },
    'crypto_weekly': {
        'type': 'cron',
        'kwargs': {'day_of_week': 'mon', 'hour': 5, 'minute': 0},
    },
    # 期货（日盘 + 夜盘）
    'futures_minute': {
        'type': 'cron',
        'kwargs': {'hour': '9-14,21-23,0-2', 'minute': '*/5', 'day_of_week': 'mon-fri'},
    },
    'futures_daily': {
        'type': 'cron',
        'kwargs': {'hour': 15, 'minute': 30, 'day_of_week': 'mon-fri'},
    },
    'futures_weekly': {
        'type': 'cron',
        'kwargs': {'day_of_week': 'sat', 'hour': 8, 'minute': 0},
    },
    # 社交简报
    'x_briefing': {
        'type': 'cron',
        'kwargs': {'hour': 8, 'minute': 50},
    },
    'weibo_briefing': {
        'type': 'cron',
        'kwargs': {'hour': '8,20', 'minute': 7},
    },
    # 行情早报：每天 09:31
    'market_briefing': {
        'type': 'cron',
        'kwargs': {'hour': 9, 'minute': 31},
    },
    # 公众号 AI 早报：每天 09:35
    'morning_briefing': {
        'type': 'cron',
        'kwargs': {'hour': 9, 'minute': 35},
    },
}
