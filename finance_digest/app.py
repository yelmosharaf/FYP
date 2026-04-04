#!/usr/bin/env python3
"""
Finance Digest — Flask web app
Mobile-first UI: view today's articles and trigger email delivery.
"""

import os
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from digest import gather_articles, build_pdf, send_email

load_dotenv()

app = Flask(__name__)

# Simple in-memory cache so repeated page loads don't re-fetch feeds
_cache: dict = {"articles": None, "fetched_at": None}
_cache_ttl_seconds = 1800  # 30 minutes


def get_articles(force: bool = False):
    now = datetime.utcnow()
    if (
        not force
        and _cache["articles"] is not None
        and _cache["fetched_at"] is not None
        and (now - _cache["fetched_at"]).seconds < _cache_ttl_seconds
    ):
        return _cache["articles"]

    articles = gather_articles()
    _cache["articles"] = articles
    _cache["fetched_at"] = now
    return articles


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/articles")
def api_articles():
    force = request.args.get("refresh") == "1"
    try:
        articles = get_articles(force=force)
        fetched_at = (
            _cache["fetched_at"].strftime("%H:%M UTC") if _cache["fetched_at"] else "—"
        )
        return jsonify({"articles": articles, "fetched_at": fetched_at, "count": len(articles)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    try:
        articles = get_articles()
        if not articles:
            return jsonify({"error": "No articles to send."}), 400

        pdf_bytes = build_pdf(articles)
        send_email(pdf_bytes, len(articles))
        return jsonify({"ok": True, "sent_to": os.getenv("RECIPIENT_EMAIL", "elmusharf@gmail.com")})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
