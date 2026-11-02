import base64
import os
import re
import uuid
from pathlib import PurePosixPath

import requests
from flask import Flask, abort, jsonify, render_template, request, Response

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-before-deploying")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # owner/repository
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD", "")
GITHUB_API = "https://api.github.com"


def github_headers():
    if not GITHUB_TOKEN or not GITHUB_REPO or "/" not in GITHUB_REPO:
        raise RuntimeError("Set GITHUB_TOKEN and GITHUB_REPO (owner/repository).")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def repo_url(path=""):
    path = path.strip("/")
    base = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents"
    return f"{base}/{path}" if path else base


def github_get(path):
    response = requests.get(
        repo_url(path),
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def github_put(path, content, message):
    encoded = base64.b64encode(content).decode("ascii")
    response = requests.put(
        repo_url(path),
        headers=github_headers(),
        json={
            "message": message,
            "content": encoded,
            "branch": GITHUB_BRANCH,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def github_file_bytes(path):
    item = github_get(path)
    if not item or item.get("type") != "file":
        abort(404)
    # GitHub Contents API returns base64 for ordinary files up to its size limit.
    if item.get("encoding") == "base64" and item.get("content"):
        return base64.b64decode(item["content"])
    download_url = item.get("download_url")
    if not download_url:
        abort(404)
    response = requests.get(download_url, timeout=30)
    response.raise_for_status()
    return response.content


def safe_slug(name):
    stem = PurePosixPath(name.replace("\\", "/")).name.rsplit(".", 1)[0]
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-_").lower()
    return (stem[:40] or "game") + "-" + uuid.uuid4().hex[:6]


def authorized_upload():
    supplied = request.headers.get("X-Upload-Password") or request.form.get("password", "")
    return bool(UPLOAD_PASSWORD) and supplied == UPLOAD_PASSWORD


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/games")
def api_games():
    try:
        entries = github_get("games") or []
        games = []
        for entry in entries:
            if entry.get("type") != "dir":
                continue
            slug = entry["name"]
            title_item = github_get(f"games/{slug}/title.txt")
            title = " ".join(title_item.get("name", "").split()) if False else slug
            if title_item:
                try:
                    title = base64.b64decode(title_item.get("content", "")).decode("utf-8").strip() or slug
                except Exception:
                    title = slug
            children = github_get(f"games/{slug}") or []
            cover = next((x["name"] for x in children if x["name"].startswith("cover.")), None)
            games.append({"id": slug, "title": title, "cover": f"/cover/{slug}" if cover else None})
        games.sort(key=lambda x: x["title"].lower())
        return jsonify(games)
    except requests.RequestException as exc:
        return jsonify({"error": f"GitHub API error: {exc}"}), 502
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/upload")
def api_upload():
    if not authorized_upload():
        return jsonify({"error": "Upload password is missing or incorrect."}), 401

    html_file = request.files.get("html")
    image_file = request.files.get("image")
    if not html_file or not html_file.filename.lower().endswith((".html", ".htm")):
        return jsonify({"error": "Choose an .html or .htm file."}), 400

    html_bytes = html_file.read()
    if not html_bytes:
        return jsonify({"error": "The HTML file is empty."}), 400
    if len(html_bytes) > 10 * 1024 * 1024:
        return jsonify({"error": "HTML files must be 10 MB or smaller."}), 413

    title = (request.form.get("title") or html_file.filename.rsplit(".", 1)[0]).strip()
    title = title[:80] or "Untitled game"
    slug = safe_slug(title)

    try:
        github_put(f"games/{slug}/title.txt", title.encode("utf-8"), f"Add {title} title")
        github_put(f"games/{slug}/index.html", html_bytes, f"Upload {title} HTML")
        if image_file and image_file.filename:
            ext = os.path.splitext(image_file.filename)[1].lower()
            allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            if ext not in allowed:
                return jsonify({"error": "Image must be PNG, JPG, WEBP, or GIF."}), 400
            image_bytes = image_file.read()
            if len(image_bytes) > 8 * 1024 * 1024:
                return jsonify({"error": "Cover images must be 8 MB or smaller."}), 413
            github_put(f"games/{slug}/cover{ext}", image_bytes, f"Add {title} cover image")
        return jsonify({"ok": True, "id": slug, "title": title, "play_url": f"/play/{slug}"}), 201
    except requests.RequestException as exc:
        detail = getattr(exc.response, "text", "") if getattr(exc, "response", None) is not None else str(exc)
        return jsonify({"error": f"GitHub upload failed: {detail[:500]}"}), 502
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/cover/<slug>")
def cover(slug):
    try:
        children = github_get(f"games/{slug}") or []
        cover_item = next((x for x in children if x.get("name", "").startswith("cover.")), None)
        if not cover_item:
            abort(404)
        data = github_file_bytes(f"games/{slug}/{cover_item['name']}")
        ext = os.path.splitext(cover_item["name"])[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "application/octet-stream")
        return Response(data, mimetype=mime, headers={"Cache-Control": "public, max-age=300"})
    except requests.RequestException:
        abort(502)


@app.get("/play/<slug>")
def play(slug):
    item = github_get(f"games/{slug}/title.txt")
    if not item:
        abort(404)
    title = base64.b64decode(item.get("content", "")).decode("utf-8").strip() or slug
    return render_template("play.html", game_id=slug, title=title)


@app.get("/content/<slug>")
def game_content(slug):
    try:
        data = github_file_bytes(f"games/{slug}/index.html")
        # The HTML is sandboxed by the parent play page's iframe.
        return Response(data, mimetype="text/html; charset=utf-8",
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Cache-Control": "no-store"})
    except requests.RequestException:
        abort(502)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
