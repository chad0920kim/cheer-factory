from flask import Flask, render_template, request, jsonify, session
import json
from pathlib import Path
import secrets
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

POSTS_DIR = Path(__file__).parent / "posts"

def load_posts(lang=None):
    """posts 폴더에서 모든 포스트를 로드 (txt 형식 지원)"""
    posts = []
    if POSTS_DIR.exists():
        for file in sorted(POSTS_DIR.glob("*.txt"), reverse=True):
            filename = file.stem

            # template 파일 제외
            if filename == "template":
                continue

            # 언어 필터링 (파일명이 -ko 또는 -en으로 끝나는 경우)
            file_lang = None
            if filename.endswith("-ko"):
                file_lang = "ko"
            elif filename.endswith("-en"):
                file_lang = "en"

            if lang and file_lang and file_lang != lang:
                continue

            with open(file, "r", encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
                # 첫 줄: 제목, 나머지: 본문
                title = lines[0] if lines else "Untitled"
                content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

                # 파일명에서 날짜 추출 (2026-01-10-001-ko.txt -> 2026-01-10)
                date = "-".join(filename.split("-")[:3]) if "-" in filename else filename

                # likes 파일 확인
                likes_file = POSTS_DIR / f"{filename}.likes"
                likes = int(likes_file.read_text()) if likes_file.exists() else 0

                posts.append({
                    "id": filename,
                    "title": title,
                    "date": date,
                    "content": content,
                    "likes": likes,
                    "lang": file_lang
                })
    return posts

def search_posts(posts, query):
    """포스트 검색"""
    if not query:
        return posts
    query = query.lower()
    return [p for p in posts if query in p.get("title", "").lower() or query in p.get("content", "").lower()]

@app.route("/")
def index():
    lang = request.args.get("lang", "ko")  # 기본값: 한국어
    posts = load_posts(lang=lang)
    query = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    per_page = 5

    if query:
        posts = search_posts(posts, query)

    total_posts = len(posts)
    total_pages = max(1, (total_posts + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    paginated_posts = posts[start:end]

    return render_template(
        "index.html",
        posts=paginated_posts,
        query=query,
        page=page,
        total_pages=total_pages,
        total_posts=total_posts,
        lang=lang
    )

@app.route("/like/<post_id>", methods=["POST"])
def like_post(post_id):
    post_file = POSTS_DIR / f"{post_id}.txt"
    if not post_file.exists():
        return jsonify({"error": "Post not found"}), 404

    if "liked_posts" not in session:
        session["liked_posts"] = []

    likes_file = POSTS_DIR / f"{post_id}.likes"
    current_likes = int(likes_file.read_text()) if likes_file.exists() else 0

    liked = post_id in session["liked_posts"]

    if liked:
        session["liked_posts"].remove(post_id)
        current_likes = max(0, current_likes - 1)
        liked = False
    else:
        session["liked_posts"].append(post_id)
        current_likes += 1
        liked = True

    session.modified = True
    likes_file.write_text(str(current_likes))

    return jsonify({"likes": current_likes, "liked": liked})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
