"""
Sends a Telegram message whenever NEW cars appear on opl.co.il.

Local:  python opl_monitor.py            (one check)
        python opl_monitor.py --loop 30  (check every 30 minutes)
Cloud:  reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from environment variables.

Needs opl_scraper.py in the same folder.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from opl_scraper import scrape

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "opl_state.json"
CONFIG_FILE = HERE / "telegram_config.json"

# Column names used by the site (unicode escapes so the source has no Hebrew)
MAKER = "\u05d9\u05e6\u05e8\u05df"
MODEL = "\u05d3\u05d2\u05dd"
YEAR = "\u05e9\u05e0\u05d4"
KM = "\u05e7\u05f4\u05de"
COLOR = "\u05e6\u05d1\u05e2"
PRICE = "\u05de\u05d7\u05d9\u05e8 \u05de\u05db\u05d9\u05e8\u05d4"
LICENCE = "\u05de\u05e1\u05e4\u05e8 \u05e8\u05d9\u05e9\u05d5\u05d9"


# ---------- Telegram ----------
def tg(token, method, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def ensure_config():
    """Cloud: env vars. Local: telegram_config.json (asks for token + finds chat id once)."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return {"token": token, "chat_id": chat_id}

    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    if not cfg.get("token"):
        cfg["token"] = input("Paste the bot token from BotFather: ").strip()
    while not cfg.get("chat_id"):
        try:
            updates = tg(cfg["token"], "getUpdates").get("result", [])
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Telegram rejected the token (HTTP {e.code}). "
                             "Check it and delete telegram_config.json if it exists.")
        chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
        if chats:
            cfg["chat_id"] = str(chats[-1])
            print("Found chat id:", cfg["chat_id"])
        else:
            print("No messages found yet.")
            print("1) Open your bot in Telegram  2) Send it: /start  3) Come back here")
            input("Then press Enter... ")
    CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def send(cfg, text):
    chunk = ""
    for line in text.splitlines() + [None]:
        if line is None or len(chunk) + len(line) > 3800:
            if chunk.strip():
                tg(cfg["token"], "sendMessage", chat_id=cfg["chat_id"], text=chunk,
                   disable_web_page_preview="true")
                time.sleep(0.5)
            chunk = ""
        if line is not None:
            chunk += line + "\n"


# ---------- Cars ----------
def car_key(rec):
    return rec.get(LICENCE) or "|".join(rec.get(k, "") for k in (MAKER, MODEL, YEAR, KM, COLOR))


def describe(rec):
    return (f"- {rec.get(MAKER, '')} {rec.get(MODEL, '')} {rec.get(YEAR, '')} | "
            f"{rec.get(KM, '')} km | {rec.get(COLOR, '')} | {rec.get(PRICE, '')}")


def check(cfg, show=False):
    rows = scrape(show)
    new = {car_key(r): r for r in rows}
    try:
        old = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else None
    except ValueError:
        old = None

    def save():
        STATE_FILE.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")

    if old is None:
        save()
        send(cfg, f"Monitoring started. Saved {len(new)} cars. "
                  "From now on you only get NEW cars.")
        return
    if len(new) < 0.5 * len(old):          # partial page load - ignore it
        print(f"Only {len(new)} cars (was {len(old)}), skipping.")
        return

    added = [new[k] for k in new if k not in old]
    if added:
        send(cfg, f"{len(added)} NEW cars ({datetime.now():%d/%m %H:%M})\n"
                  + "\n".join(describe(c) for c in added))
        print(f"Sent {len(added)} new cars")
    else:
        print("No new cars.")
    save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--loop", type=int, metavar="MIN", help="repeat every MIN minutes")
    args = ap.parse_args()

    cfg = ensure_config()
    while True:
        failed = False
        try:
            check(cfg, args.show)
        except Exception as e:
            failed = True
            print("Check failed:", e)
        if not args.loop:
            sys.exit(1 if failed else 0)      # makes a failed cloud run show up red
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()
