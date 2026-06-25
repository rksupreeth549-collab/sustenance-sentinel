"""Notification transport with quick-reply buttons for the ladder.

Backends: console (default, offline demo), telegram, twilio. Buttons degrade to
a "(reply: Ate / Order / Skip)" hint on channels without rich buttons.
"""
from __future__ import annotations

import os

LADDER_BUTTONS = ["Ate ✅", "Order for me 🍱", "Skip 🙅"]


class ConsoleChannel:
    def send(self, to: str, text: str, buttons: list[str] | None = None) -> None:
        line = f"[MSG -> {to}] {text}"
        if buttons:
            line += "   {" + " | ".join(buttons) + "}"
        _safe_print(line)


def _safe_print(line: str) -> None:
    """Print without crashing on consoles (Windows cp1252) that can't encode emoji."""
    import sys
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode(enc, "replace").decode(enc))


class TelegramChannel:
    def __init__(self, token: str):
        self.token = token

    def send(self, to: str, text: str, buttons: list[str] | None = None) -> None:
        import json
        import urllib.request
        payload = {"chat_id": to, "text": text}
        if buttons:
            payload["reply_markup"] = json.dumps(
                {"keyboard": [[{"text": b}] for b in buttons],
                 "one_time_keyboard": True, "resize_keyboard": True}
            )
        data = urllib.parse.urlencode(payload).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        urllib.request.urlopen(urllib.request.Request(url, data=data))


class TwilioChannel:
    def __init__(self, sid: str, token: str, from_: str):
        self.sid, self.token, self.from_ = sid, token, from_

    def send(self, to: str, text: str, buttons: list[str] | None = None) -> None:
        from twilio.rest import Client  # optional dep
        body = text
        if buttons:
            body += "\nReply: " + " / ".join(b.split()[0] for b in buttons)
        Client(self.sid, self.token).messages.create(to=to, from_=self.from_, body=body)


def get_channel(kind: str):
    """kind: 'console' | 'telegram' | 'twilio'."""
    if kind == "telegram" and os.getenv("TELEGRAM_BOT_TOKEN"):
        return TelegramChannel(os.environ["TELEGRAM_BOT_TOKEN"])
    if kind == "twilio" and os.getenv("TWILIO_ACCOUNT_SID"):
        return TwilioChannel(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
            os.environ["TWILIO_FROM"],
        )
    return ConsoleChannel()  # safe default
