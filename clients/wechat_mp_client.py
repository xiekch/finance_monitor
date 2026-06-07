import logging
import time
from typing import Optional

import requests

from config.settings import WECHAT_MP_CONFIG

BASE_URL = "https://api.weixin.qq.com"


class WechatMPError(Exception):
    def __init__(self, errcode: int, errmsg: str):
        self.errcode = errcode
        self.errmsg = errmsg
        super().__init__(f"WeChat MP API error {errcode}: {errmsg}")


class WechatMPClient:

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        thumb_media_id: str = "",
    ):
        self.app_id = app_id or WECHAT_MP_CONFIG.get("app_id", "")
        self.app_secret = app_secret or WECHAT_MP_CONFIG.get("app_secret", "")
        self.thumb_media_id = thumb_media_id or WECHAT_MP_CONFIG.get("thumb_media_id", "")
        self.session = requests.Session()
        self._token: Optional[str] = None
        self._token_expires: float = 0

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def _get_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires:
            return self._token

        resp = self.session.get(
            f"{BASE_URL}/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self.app_id,
                "secret": self.app_secret,
            },
            timeout=10,
        )
        data = resp.json()
        if "access_token" not in data:
            raise WechatMPError(
                data.get("errcode", -1), data.get("errmsg", "unknown"),
            )
        self._token = data["access_token"]
        self._token_expires = now + data.get("expires_in", 7200) - 300
        logging.info("[WechatMPClient] access_token 刷新成功")
        return self._token

    def _api_post(self, path: str, json_body: dict) -> dict:
        token = self._get_access_token()
        resp = self.session.post(
            f"{BASE_URL}{path}?access_token={token}",
            json=json_body,
            timeout=30,
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WechatMPError(data["errcode"], data.get("errmsg", ""))
        return data

    def add_draft(
        self,
        title: str,
        content_html: str,
        author: str = "",
        digest: str = "",
    ) -> str:
        if not self.thumb_media_id:
            raise WechatMPError(-1, "未配置封面图 thumb_media_id")

        article = {
            "title": title,
            "author": author,
            "content": content_html,
            "digest": digest,
            "thumb_media_id": self.thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        data = self._api_post("/cgi-bin/draft/add", {"articles": [article]})
        media_id = data.get("media_id", "")
        logging.info(f"[WechatMPClient] 草稿创建成功 media_id={media_id}")
        return media_id

    def publish(self, media_id: str) -> str:
        data = self._api_post(
            "/cgi-bin/freepublish/submit", {"media_id": media_id},
        )
        publish_id = data.get("publish_id", "")
        logging.info(f"[WechatMPClient] 发布提交成功 publish_id={publish_id}")
        return publish_id
