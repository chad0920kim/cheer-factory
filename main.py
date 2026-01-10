from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
from pathlib import Path
import secrets
import os
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# Gemini AI 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

# GitHub 설정
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# Admin 비밀번호
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "cheer2026")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))

POSTS_DIR = Path(__file__).parent / "posts"

# AI 글 생성용 프롬프트
SYSTEM_PROMPT = """당신은 'Cheer Factory'라는 익명 블로그의 작가입니다.

## 페르소나
- 10년 넘게 인사담당자로 일해온 40대 후반 남성
- 수많은 사람들의 입사와 퇴사, 성장과 좌절을 곁에서 지켜봐온 경험
- 최근 바이브코딩에 빠져 새로운 도전을 즐기는 중
- 따뜻하지만 현실적인 시선으로 직장생활과 인생을 바라봄

## 글 스타일
- 짧고 담백한 문체 (3-5문장 정도의 짧은 단락)
- 과하지 않은 위로와 공감
- 가끔 유머나 자조적인 농담
- "~더라", "~거든요" 같은 구어체 사용

## 주제
주어진 주제나 키워드를 바탕으로 직장인들의 일상, 고민, 작은 행복에 대해 씁니다."""

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

# ============ Admin 기능 ============

def generate_post_content(topic=None):
    """AI로 글 생성"""
    prompt = f"""{SYSTEM_PROMPT}

다음 주제로 블로그 글을 작성해주세요: {topic if topic else '자유 주제'}

JSON 형식으로 응답해주세요:
{{"title": "글 제목", "content": "글 본문"}}"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    return json.loads(text.strip())

def translate_to_english(title, content):
    """한국어를 영어로 번역"""
    prompt = f"""다음 한국어 블로그 글을 영어로 자연스럽게 번역해주세요.

제목: {title}

본문:
{content}

JSON 형식으로 응답해주세요:
{{"title": "영어 제목", "content": "영어 본문"}}"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    return json.loads(text.strip())

def get_existing_posts_count(date):
    """GitHub에서 해당 날짜의 포스트 수 확인"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return 0

    files = response.json()
    count = sum(1 for f in files if f["name"].startswith(date) and f["name"].endswith("-ko.txt"))
    return count

def publish_to_github(title_ko, content_ko, title_en, content_en):
    """GitHub에 포스트 배포"""
    today = datetime.now().strftime("%Y-%m-%d")
    post_num = get_existing_posts_count(today) + 1

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 한국어 파일
    filename_ko = f"{today}-{post_num:03d}-ko.txt"
    file_content_ko = f"{title_ko}\n\n{content_ko}"
    content_base64_ko = base64.b64encode(file_content_ko.encode("utf-8")).decode("utf-8")

    url_ko = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{filename_ko}"
    response_ko = requests.put(url_ko, headers=headers, json={
        "message": f"Add post (KO): {title_ko}",
        "content": content_base64_ko,
        "branch": "master"
    })

    # 영어 파일
    filename_en = f"{today}-{post_num:03d}-en.txt"
    file_content_en = f"{title_en}\n\n{content_en}"
    content_base64_en = base64.b64encode(file_content_en.encode("utf-8")).decode("utf-8")

    url_en = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{filename_en}"
    response_en = requests.put(url_en, headers=headers, json={
        "message": f"Add post (EN): {title_en}",
        "content": content_base64_en,
        "branch": "master"
    })

    return response_ko.status_code == 201 and response_en.status_code == 201

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        error = "Wrong password"
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("index"))

@app.route("/admin/generate", methods=["POST"])
def admin_generate():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    topic = request.json.get("topic", "")
    try:
        post = generate_post_content(topic)
        return jsonify(post)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/publish", methods=["POST"])
def admin_publish():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    title_ko = data.get("title_ko", "")
    content_ko = data.get("content_ko", "")

    if not title_ko or not content_ko:
        return jsonify({"error": "Title and content required"}), 400

    try:
        # 영어 번역
        translated = translate_to_english(title_ko, content_ko)

        # GitHub 배포
        success = publish_to_github(
            title_ko, content_ko,
            translated["title"], translated["content"]
        )

        if success:
            return jsonify({"success": True, "message": "Published!"})
        else:
            return jsonify({"error": "GitHub publish failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
