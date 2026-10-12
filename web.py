import hashlib
import hmac
import json
import os
import sqlite3
import time
from urllib.parse import parse_qsl

import requests
from flask import Flask, jsonify, render_template, request

def validate_webapp_init_data(init_data: str, bot_token: str):
    """Validate Telegram Mini App initData signature; return parsed fields or None."""
    if not init_data:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(data.get("auth_date", "0"))
        if auth_date <= 0 or abs(time.time() - auth_date) > 86400:
            return None

        user = json.loads(data.get("user", "{}"))
        if not user.get("id"):
            return None
        return {"user": user, "auth_date": auth_date}
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

def create_web_app(bot_token, db_path, channel_username, group_url, youtube_url):
    app = Flask(__name__, template_folder="templates")
    app.config["BOT_TOKEN"] = bot_token
    app.config["DB_PATH"] = db_path
    app.config["CHANNEL_USERNAME"] = channel_username
    app.config["GROUP_URL"] = group_url
    app.config["YOUTUBE_URL"] = youtube_url

    def db():
        conn = sqlite3.connect(app.config["DB_PATH"], timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

    def telegram_api(method, payload):
        response = requests.post(
            f"https://api.telegram.org/bot{app.config['BOT_TOKEN']}/{method}",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram API error"))
        return data["result"]

    @app.get("/")
    def home():
        token = request.args.get("token", "")
        return render_template(
            "index.html",
            token=token,
            channel_username=app.config["CHANNEL_USERNAME"],
            youtube_url=app.config["YOUTUBE_URL"],
            group_url=app.config["GROUP_URL"],
        )

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "service": "Saksham JoinGate"})

    @app.post("/api/verify")
    def verify():
        body = request.get_json(silent=True) or {}
        init_data = body.get("initData", "")
        token = body.get("token", "")
        validated = validate_webapp_init_data(init_data, app.config["BOT_TOKEN"])
        if not validated:
            return jsonify({
                "ok": False,
                "code": "OPEN_IN_TELEGRAM",
                "message": "Please open this page from the Verify button inside the Telegram bot chat."
            }), 401

        user_id = int(validated["user"]["id"])
        with db() as conn:
            pending = conn.execute(
                "SELECT * FROM pending WHERE token=?", (token,)
            ).fetchone()

        if not pending or int(pending["user_id"]) != user_id:
            return jsonify({
                "ok": False,
                "code": "INVALID_LINK",
                "message": "This verification link is invalid or expired. Please request a fresh link in your group."
            }), 403

        try:
            member = telegram_api("getChatMember", {
                "chat_id": app.config["CHANNEL_USERNAME"],
                "user_id": user_id,
            })
        except Exception as exc:
            app.logger.exception("Channel membership lookup failed")
            return jsonify({
                "ok": False,
                "code": "BOT_CHANNEL_PERMISSION",
                "message": "Membership check failed. Please try again shortly. If it keeps happening, the group admin must make the bot an administrator in the required channel."
            }), 502

        status = member.get("status", "left")
        if status not in ("member", "administrator", "creator"):
            return jsonify({
                "ok": False,
                "code": "NOT_JOINED",
                "message": "We couldn't find your membership in the required Telegram channel. Join the channel, return here, then tap verify again."
            }), 200

        try:
            telegram_api("restrictChatMember", {
                "chat_id": int(pending["chat_id"]),
                "user_id": user_id,
                "permissions": {
                    "can_send_messages": True,
                    "can_send_audios": True,
                    "can_send_documents": True,
                    "can_send_photos": True,
                    "can_send_videos": True,
                    "can_send_video_notes": True,
                    "can_send_voice_notes": True,
                    "can_send_polls": True,
                    "can_send_other_messages": True,
                    "can_add_web_page_previews": True
                },
                "use_independent_chat_permissions": False
            })
        except Exception:
            app.logger.exception("Could not unmute verified member")
            return jsonify({
                "ok": False,
                "code": "UNMUTE_FAILED",
                "message": "Membership is confirmed, but I couldn't unmute you. Please ask a group admin to check the bot's Restrict Members permission."
            }), 502

        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO verified(chat_id,user_id,verified_at) VALUES(?,?,datetime('now'))",
                (int(pending["chat_id"]), user_id),
            )
            conn.execute("DELETE FROM pending WHERE token=?", (token,))

        return jsonify({
            "ok": True,
            "message": "Membership verified! You are now unmuted. You can return to your Telegram group."
        })

    return app
