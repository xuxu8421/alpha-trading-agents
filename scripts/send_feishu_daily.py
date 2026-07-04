"""Send a generated daily research brief to a Feishu custom-bot webhook.

Secrets are loaded from the project's .env file and are never accepted on the
command line, where they could leak into shell history or process listings.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


def _signature(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_markdown(markdown: str, title: str) -> None:
    load_dotenv()
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    secret = os.getenv("FEISHU_WEBHOOK_SECRET", "").strip()
    if not webhook:
        raise RuntimeError("FEISHU_WEBHOOK_URL is not configured in .env")

    payload: dict[str, object] = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [{"tag": "markdown", "content": markdown}],
        },
    }
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _signature(timestamp, secret)

    response = requests.post(webhook, json=payload, timeout=20)
    response.raise_for_status()
    result = response.json()
    if result.get("code", result.get("StatusCode", 0)) != 0:
        raise RuntimeError(f"Feishu webhook rejected the message: {result}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send daily research to Feishu")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--title", default="A股每日投研总结")
    args = parser.parse_args()
    markdown = args.input.read_text(encoding="utf-8").strip()
    if not markdown:
        raise RuntimeError(f"Daily brief is empty: {args.input}")
    send_markdown(markdown, args.title)
    print(f"Feishu message sent: {args.input}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
