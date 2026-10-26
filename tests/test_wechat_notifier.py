import json

from clients.wechat_notifier import WeChatNotifier


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.bodies = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.bodies.append(json.loads(data))
        return FakeResponse(self.payloads.pop(0) if self.payloads else {"errcode": 0})


def _notifier(payloads=()):
    notifier = WeChatNotifier(["https://example.com/hook"])
    notifier.session = FakeSession(payloads)
    return notifier


def test_errcode_nonzero_is_failure():
    notifier = _notifier([{"errcode": 40058, "errmsg": "content exceed max length"}])
    assert notifier.send_markdown("hello") is False
    notifier = _notifier([{"errcode": 93000, "errmsg": "invalid webhook url"}])
    assert notifier._post_text("hello") is False


def test_markdown_split_by_bytes_keeps_everything():
    notifier = _notifier()
    content = "\n\n".join(f"第{i}段" + "中" * 300 for i in range(12))
    assert notifier.send_markdown(content, inter_part_sleep=0) is True
    bodies = [b["markdown"]["content"] for b in notifier.session.bodies]
    assert len(bodies) > 1
    assert all(len(b.encode("utf-8")) <= 4096 for b in bodies)
    joined = "".join(bodies)
    assert all(f"第{i}段" in joined for i in range(12))


def test_short_markdown_sent_once_without_header():
    notifier = _notifier()
    assert notifier.send_markdown("**短消息**") is True
    assert notifier.session.bodies == [{"msgtype": "markdown", "markdown": {"content": "**短消息**"}}]
