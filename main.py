from flask import Flask, render_template, request, jsonify, session
import json
from pathlib import Path
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

POSTS_DIR = Path(__file__).parent / "posts"

def load_posts():
    """posts 폴더에서 모든 포스트를 로드"""
    posts = []
    if POSTS_DIR.exists():
        for file in sorted(POSTS_DIR.glob("*.json"), reverse=True):
            with open(file, "r", encoding="utf-8") as f:
                post = json.load(f)
                post["id"] = file.stem
                posts.append(post)
    return posts

def search_posts(posts, query):
    """포스트 검색"""
    if not query:
        return posts
    query = query.lower()
    return [p for p in posts if query in p.get("title", "").lower() or query in p.get("content", "").lower()]

@app.route("/")
def index():
    posts = load_posts()
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
        total_posts=total_posts
    )

@app.route("/like/<post_id>", methods=["POST"])
def like_post(post_id):
    post_file = POSTS_DIR / f"{post_id}.json"
    if not post_file.exists():
        return jsonify({"error": "Post not found"}), 404

    if "liked_posts" not in session:
        session["liked_posts"] = []

    with open(post_file, "r", encoding="utf-8") as f:
        post = json.load(f)

    liked = post_id in session["liked_posts"]

    if liked:
        session["liked_posts"].remove(post_id)
        post["likes"] = max(0, post.get("likes", 0) - 1)
        liked = False
    else:
        session["liked_posts"].append(post_id)
        post["likes"] = post.get("likes", 0) + 1
        liked = True

    session.modified = True

    with open(post_file, "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)

    return jsonify({"likes": post["likes"], "liked": liked})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
