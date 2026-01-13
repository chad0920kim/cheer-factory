from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import secrets
import os
import base64
import requests
import cloudinary
import cloudinary.uploader
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
import time
from supabase import create_client, Client

load_dotenv()

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 메모리 캐시
_posts_cache = {
    "data": None,
    "timestamp": 0,
    "ttl": 60  # 60초 캐시
}

# Gemini AI 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
model = None
image_model = None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    image_model = genai.GenerativeModel("gemini-2.0-flash-exp-image-generation")

# GitHub 설정
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# Cloudinary 설정
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# Admin 비밀번호 (환경변수 필수)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Pexels API 설정
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# Google Analytics ID (환경변수)
GA_ID = os.getenv("GA_ID")

# 사이트 URL
SITE_URL = os.getenv("SITE_URL", "https://cheer-factory.onrender.com")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))

# AI 글 생성용 기본 프롬프트
DEFAULT_PROMPT = """당신은 'Cheer Factory'라는 익명 블로그의 작가입니다.

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

def get_system_prompt():
    """GitHub에서 프롬프트 로드, 없으면 기본값 사용"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return DEFAULT_PROMPT

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config/prompt.txt"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            file_data = response.json()
            content = base64.b64decode(file_data["content"]).decode("utf-8")
            return content.strip()
    except:
        pass

    return DEFAULT_PROMPT

def parse_post_content(text):
    """포스트 텍스트를 파싱하여 메타데이터와 본문 분리"""
    lines = text.strip().split("\n")
    title = lines[0] if lines else "Untitled"

    tags = []
    image_url = ""
    content_lines = []

    for line in lines[1:]:
        line_stripped = line.strip()
        if line_stripped.startswith("TAGS:"):
            tags = [t.strip() for t in line_stripped[5:].split(",") if t.strip()]
        elif line_stripped.startswith("IMAGE:"):
            image_url = line_stripped[6:].strip()
        else:
            content_lines.append(line)

    content = "\n".join(content_lines).strip()
    return title, content, tags, image_url

def get_posts_index():
    """GitHub에서 posts/index.json 가져오기"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/index.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            file_data = response.json()
            content = base64.b64decode(file_data["content"]).decode("utf-8")
            return json.loads(content)
    except:
        pass
    return None

def save_posts_index(index_data):
    """GitHub에 posts/index.json 저장"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/index.json"

    # 기존 SHA 가져오기
    sha = None
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        sha = response.json().get("sha")

    # 저장
    content_base64 = base64.b64encode(json.dumps(index_data, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update posts index",
        "content": content_base64,
        "branch": "master"
    }
    if sha:
        payload["sha"] = sha

    save_response = requests.put(url, headers=headers, json=payload)
    return save_response.status_code in [200, 201]

def invalidate_cache():
    """캐시 무효화"""
    _posts_cache["data"] = None
    _posts_cache["timestamp"] = 0

def load_posts(lang=None):
    """GitHub에서 포스트 로드 (index.json 사용, 캐싱 적용)"""
    global _posts_cache

    # 캐시 확인
    now = time.time()
    if _posts_cache["data"] is not None and (now - _posts_cache["timestamp"]) < _posts_cache["ttl"]:
        all_posts = _posts_cache["data"]
    else:
        # index.json에서 로드 시도
        index_data = get_posts_index()

        if index_data and "posts" in index_data:
            all_posts = index_data["posts"]
        else:
            # index.json이 없으면 기존 방식으로 로드 후 index.json 생성
            all_posts = load_posts_legacy()
            if all_posts:
                save_posts_index({"posts": all_posts, "updated": datetime.now().isoformat()})

        # 캐시 저장
        _posts_cache["data"] = all_posts
        _posts_cache["timestamp"] = now

    # 언어 필터링
    if lang:
        return [p for p in all_posts if p.get("lang") == lang]
    return all_posts

def load_posts_legacy():
    """GitHub에서 모든 포스트를 로드 (기존 방식 - index.json 없을 때 사용)"""
    posts = []

    if not GITHUB_TOKEN or not GITHUB_REPO:
        return posts

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return posts

        files = response.json()
        txt_files = [f for f in files if f["name"].endswith(".txt") and f["name"] != "template.txt"]
        txt_files.sort(key=lambda x: x["name"], reverse=True)

        for f in txt_files:
            filename = f["name"][:-4]  # .txt 제거

            # 언어 필터링
            file_lang = None
            if filename.endswith("-ko"):
                file_lang = "ko"
            elif filename.endswith("-en"):
                file_lang = "en"

            # 파일 내용 가져오기 (API로 직접 가져와서 캐시 방지)
            file_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{f['name']}"
            file_response = requests.get(file_url, headers=headers)
            if file_response.status_code == 200:
                file_data = file_response.json()
                file_content = base64.b64decode(file_data["content"]).decode("utf-8")
                title, content, tags, image_url = parse_post_content(file_content)

                # 파일명에서 날짜 추출
                date = "-".join(filename.split("-")[:3]) if "-" in filename else filename

                posts.append({
                    "id": filename,
                    "title": title,
                    "date": date,
                    "content": content,
                    "tags": tags,
                    "image_url": image_url,
                    "lang": file_lang
                })
    except:
        pass

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
        lang=lang,
        ga_id=GA_ID,
        is_admin=session.get("admin_logged_in", False)
    )

# ============ SEO 기능 ============

@app.route("/sitemap.xml")
def sitemap():
    """동적 sitemap.xml 생성"""
    posts = load_posts()

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    # 메인 페이지
    xml_content += f'  <url>\n'
    xml_content += f'    <loc>{SITE_URL}/?lang=ko</loc>\n'
    xml_content += f'    <changefreq>daily</changefreq>\n'
    xml_content += f'    <priority>1.0</priority>\n'
    xml_content += f'  </url>\n'

    xml_content += f'  <url>\n'
    xml_content += f'    <loc>{SITE_URL}/?lang=en</loc>\n'
    xml_content += f'    <changefreq>daily</changefreq>\n'
    xml_content += f'    <priority>1.0</priority>\n'
    xml_content += f'  </url>\n'

    # 포스트별 URL (날짜 기반)
    added_dates = set()
    for post in posts:
        date = post.get("date", "")
        lang = post.get("lang", "ko")
        if date and f"{date}-{lang}" not in added_dates:
            added_dates.add(f"{date}-{lang}")
            xml_content += f'  <url>\n'
            xml_content += f'    <loc>{SITE_URL}/?lang={lang}</loc>\n'
            xml_content += f'    <lastmod>{date}</lastmod>\n'
            xml_content += f'    <changefreq>weekly</changefreq>\n'
            xml_content += f'    <priority>0.8</priority>\n'
            xml_content += f'  </url>\n'

    xml_content += '</urlset>'

    from flask import Response
    return Response(xml_content, mimetype='application/xml')

@app.route("/robots.txt")
def robots():
    """robots.txt 제공"""
    content = f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
    from flask import Response
    return Response(content, mimetype='text/plain')

@app.route("/google076b9b43a09642c3.html")
def google_verification():
    """Google Search Console 소유권 확인 파일"""
    return "google-site-verification: google076b9b43a09642c3.html"

# ============ 좋아요 기능 ============

@app.route("/api/like/<post_id>", methods=["POST"])
def add_like(post_id):
    """좋아요 추가"""
    if not supabase:
        return jsonify({"error": "Database not configured"}), 500

    try:
        supabase.table("likes").insert({"post_id": post_id}).execute()
        # 현재 좋아요 수 반환
        result = supabase.table("likes").select("*", count="exact").eq("post_id", post_id).execute()
        return jsonify({"success": True, "likes": result.count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/likes/<post_id>", methods=["GET"])
def get_likes(post_id):
    """좋아요 수 조회"""
    if not supabase:
        return jsonify({"likes": 0})

    try:
        result = supabase.table("likes").select("*", count="exact").eq("post_id", post_id).execute()
        return jsonify({"likes": result.count})
    except Exception as e:
        return jsonify({"error": str(e), "likes": 0})

@app.route("/api/likes/bulk", methods=["POST"])
def get_bulk_likes():
    """여러 포스트의 좋아요 수 조회"""
    if not supabase:
        return jsonify({"likes": {}})

    data = request.json
    post_ids = data.get("post_ids", [])

    if not post_ids:
        return jsonify({"likes": {}})

    try:
        likes_dict = {}
        for post_id in post_ids:
            result = supabase.table("likes").select("*", count="exact").eq("post_id", post_id).execute()
            likes_dict[post_id] = result.count
        return jsonify({"likes": likes_dict})
    except Exception as e:
        return jsonify({"error": str(e), "likes": {}})

# ============ 조회수 기능 ============

@app.route("/api/view/<post_id>", methods=["POST"])
def add_view(post_id):
    """조회수 추가"""
    if not supabase:
        return jsonify({"error": "Database not configured"}), 500

    try:
        supabase.table("views").insert({"post_id": post_id}).execute()
        result = supabase.table("views").select("*", count="exact").eq("post_id", post_id).execute()
        return jsonify({"success": True, "views": result.count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/views/<post_id>", methods=["GET"])
def get_views(post_id):
    """조회수 조회"""
    if not supabase:
        return jsonify({"views": 0})

    try:
        result = supabase.table("views").select("*", count="exact").eq("post_id", post_id).execute()
        return jsonify({"views": result.count})
    except Exception as e:
        return jsonify({"error": str(e), "views": 0})

@app.route("/api/stats/bulk", methods=["POST"])
def get_bulk_stats():
    """여러 포스트의 좋아요 + 조회수 한번에 조회"""
    if not supabase:
        return jsonify({"stats": {}})

    data = request.json
    post_ids = data.get("post_ids", [])

    if not post_ids:
        return jsonify({"stats": {}})

    try:
        stats_dict = {}
        for post_id in post_ids:
            likes_result = supabase.table("likes").select("*", count="exact").eq("post_id", post_id).execute()
            views_result = supabase.table("views").select("*", count="exact").eq("post_id", post_id).execute()
            stats_dict[post_id] = {
                "likes": likes_result.count,
                "views": views_result.count
            }
        return jsonify({"stats": stats_dict})
    except Exception as e:
        return jsonify({"error": str(e), "stats": {}})

# ============ 방명록 기능 ============

@app.route("/guestbook")
def guestbook_page():
    """방명록 페이지"""
    lang = request.args.get("lang", "ko")
    is_admin = session.get("admin_logged_in", False)
    return render_template("guestbook.html", lang=lang, is_admin=is_admin, ga_id=GA_ID)

@app.route("/api/guestbook", methods=["GET"])
def get_guestbook():
    """방명록 목록 조회"""
    if not supabase:
        return jsonify({"entries": []})

    try:
        result = supabase.table("guestbook").select("*").order("created_at", desc=True).limit(50).execute()
        entries = []
        for entry in result.data:
            entries.append({
                "id": entry["id"],
                "nickname": entry["nickname"],
                "message": entry["message"],
                "reply": entry.get("reply"),
                "created_at": entry["created_at"]
            })
        return jsonify({"entries": entries})
    except Exception as e:
        return jsonify({"error": str(e), "entries": []})

# 스팸 방지용 레이트 리미팅 (메모리 기반)
_guestbook_rate_limit = {}

@app.route("/api/guestbook", methods=["POST"])
def add_guestbook():
    """방명록 글 작성 (스팸 방지 포함)"""
    if not supabase:
        return jsonify({"error": "Database not configured"}), 500

    data = request.json
    nickname = data.get("nickname", "").strip()
    message = data.get("message", "").strip()
    honeypot = data.get("website", "")  # 허니팟 필드 (봇 탐지용)

    # 허니팟 체크 - 봇이 이 필드를 채우면 차단
    if honeypot:
        return jsonify({"success": True})  # 봇에게는 성공한 것처럼 보이게

    if not nickname or not message:
        return jsonify({"error": "Nickname and message required"}), 400

    if len(nickname) > 20:
        return jsonify({"error": "Nickname too long (max 20)"}), 400

    if len(message) > 500:
        return jsonify({"error": "Message too long (max 500)"}), 400

    # 레이트 리미팅 (IP 기반, 60초에 1회)
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()

    now = time.time()
    last_post_time = _guestbook_rate_limit.get(client_ip, 0)

    if now - last_post_time < 60:  # 60초 제한
        remaining = int(60 - (now - last_post_time))
        return jsonify({"error": f"Please wait {remaining} seconds"}), 429

    _guestbook_rate_limit[client_ip] = now

    # 오래된 레이트 리밋 기록 정리 (5분 이상)
    _guestbook_rate_limit.update({
        ip: t for ip, t in _guestbook_rate_limit.items()
        if now - t < 300
    })

    try:
        supabase.table("guestbook").insert({
            "nickname": nickname,
            "message": message
        }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/guestbook/<int:entry_id>/reply", methods=["POST"])
def reply_guestbook(entry_id):
    """방명록 댓글 (Admin 전용)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not supabase:
        return jsonify({"error": "Database not configured"}), 500

    data = request.json
    reply = data.get("reply", "").strip()

    if not reply:
        return jsonify({"error": "Reply required"}), 400

    if len(reply) > 500:
        return jsonify({"error": "Reply too long (max 500)"}), 400

    try:
        supabase.table("guestbook").update({"reply": reply}).eq("id", entry_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/guestbook/<int:entry_id>", methods=["DELETE"])
def delete_guestbook(entry_id):
    """방명록 삭제 (Admin 전용)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not supabase:
        return jsonify({"error": "Database not configured"}), 500

    try:
        supabase.table("guestbook").delete().eq("id", entry_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ Admin 기능 ============

def generate_post_content(topic=None):
    """AI로 글 생성"""
    if not model:
        raise Exception("AI model not configured. Please set GOOGLE_API_KEY.")

    system_prompt = get_system_prompt()
    prompt = f"""{system_prompt}

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
    if not model:
        raise Exception("AI model not configured. Please set GOOGLE_API_KEY.")

    prompt = f"""다음 한국어 블로그 글을 영어로 번역해주세요.

번역 스타일:
- 한국 대학생 수준의 영어로 번역
- 너무 어렵거나 고급스러운 표현은 피하고, 일상적이고 친근한 영어 사용
- 자연스럽고 읽기 쉬운 문장으로 작성

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

def add_post_to_index(post_data_ko, post_data_en):
    """index.json에 새 포스트 추가"""
    index_data = get_posts_index() or {"posts": [], "updated": ""}

    # 새 포스트를 맨 앞에 추가 (최신순)
    index_data["posts"].insert(0, post_data_ko)
    index_data["posts"].insert(1, post_data_en)
    index_data["updated"] = datetime.now().isoformat()

    save_posts_index(index_data)
    invalidate_cache()

def update_post_in_index(post_id, updated_data):
    """index.json에서 포스트 업데이트"""
    index_data = get_posts_index()
    if not index_data:
        return

    for i, post in enumerate(index_data.get("posts", [])):
        if post.get("id") == post_id:
            index_data["posts"][i].update(updated_data)
            break

    index_data["updated"] = datetime.now().isoformat()
    save_posts_index(index_data)
    invalidate_cache()

def remove_post_from_index(post_id):
    """index.json에서 포스트 삭제"""
    index_data = get_posts_index()
    if not index_data:
        return

    index_data["posts"] = [p for p in index_data.get("posts", []) if p.get("id") != post_id]
    index_data["updated"] = datetime.now().isoformat()
    save_posts_index(index_data)
    invalidate_cache()

def publish_to_github(title_ko, content_ko, title_en, content_en, tags="", image_url=""):
    """GitHub에 포스트 배포"""
    today = datetime.now().strftime("%Y-%m-%d")
    post_num = get_existing_posts_count(today) + 1

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 메타데이터 추가
    meta_lines = ""
    if tags:
        meta_lines += f"TAGS: {tags}\n"
    if image_url:
        meta_lines += f"IMAGE: {image_url}\n"

    # 한국어 파일
    filename_ko = f"{today}-{post_num:03d}-ko.txt"
    file_content_ko = f"{title_ko}\n{meta_lines}\n{content_ko}"
    content_base64_ko = base64.b64encode(file_content_ko.encode("utf-8")).decode("utf-8")

    url_ko = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{filename_ko}"
    response_ko = requests.put(url_ko, headers=headers, json={
        "message": f"Add post (KO): {title_ko}",
        "content": content_base64_ko,
        "branch": "master"
    })

    if response_ko.status_code not in [200, 201]:
        error_msg = response_ko.json().get("message", "Unknown error")
        raise Exception(f"KO publish failed: {error_msg} (status: {response_ko.status_code})")

    # 영어 파일
    filename_en = f"{today}-{post_num:03d}-en.txt"
    file_content_en = f"{title_en}\n{meta_lines}\n{content_en}"
    content_base64_en = base64.b64encode(file_content_en.encode("utf-8")).decode("utf-8")

    url_en = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{filename_en}"
    response_en = requests.put(url_en, headers=headers, json={
        "message": f"Add post (EN): {title_en}",
        "content": content_base64_en,
        "branch": "master"
    })

    if response_en.status_code not in [200, 201]:
        error_msg = response_en.json().get("message", "Unknown error")
        raise Exception(f"EN publish failed: {error_msg} (status: {response_en.status_code})")

    # index.json 업데이트
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    post_data_ko = {
        "id": filename_ko[:-4],
        "title": title_ko,
        "date": today,
        "content": content_ko,
        "tags": tags_list,
        "image_url": image_url,
        "lang": "ko"
    }
    post_data_en = {
        "id": filename_en[:-4],
        "title": title_en,
        "date": today,
        "content": content_en,
        "tags": tags_list,
        "image_url": image_url,
        "lang": "en"
    }
    add_post_to_index(post_data_ko, post_data_en)

    return True

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html")

@app.route("/admin/stats")
def admin_stats():
    """사이트 통계 조회"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    posts = load_posts()

    # 통계 계산
    total_posts = len(posts)
    posts_ko = len([p for p in posts if p.get("lang") == "ko"])
    posts_en = len([p for p in posts if p.get("lang") == "en"])
    posts_with_images = len([p for p in posts if p.get("image_url")])

    # 최근 포스트 (한국어만, 5개)
    recent_posts = [p for p in posts if p.get("lang") == "ko"][:5]

    return jsonify({
        "total_posts": total_posts,
        "posts_ko": posts_ko,
        "posts_en": posts_en,
        "posts_with_images": posts_with_images,
        "recent_posts": recent_posts,
        "ga_configured": bool(GA_ID),
        "ga_id": GA_ID[:10] + "..." if GA_ID and len(GA_ID) > 10 else GA_ID
    })

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if not ADMIN_PASSWORD:
        error = "Admin not configured"
    elif request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        error = "Wrong password"
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("index"))

@app.route("/admin/prompt", methods=["GET"])
def admin_get_prompt():
    """현재 프롬프트 가져오기"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    prompt = get_system_prompt()
    return jsonify({"prompt": prompt})

@app.route("/admin/prompt", methods=["POST"])
def admin_save_prompt():
    """프롬프트 저장 (GitHub에)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    prompt = data.get("prompt", "")

    if not prompt.strip():
        return jsonify({"error": "Prompt cannot be empty"}), 400

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config/prompt.txt"

    # 기존 파일 SHA 가져오기 (있으면)
    sha = None
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        sha = response.json().get("sha")

    # 파일 저장
    content_base64 = base64.b64encode(prompt.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update AI prompt",
        "content": content_base64,
        "branch": "master"
    }
    if sha:
        payload["sha"] = sha

    save_response = requests.put(url, headers=headers, json=payload)

    if save_response.status_code in [200, 201]:
        return jsonify({"success": True, "message": "Prompt saved!"})
    else:
        error_msg = save_response.json().get("message", "Unknown error")
        return jsonify({"error": error_msg}), 500

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

    tags = data.get("tags", "")
    image_url = data.get("image_url", "")

    try:
        # 영어 번역
        translated = translate_to_english(title_ko, content_ko)

        # GitHub 배포
        success = publish_to_github(
            title_ko, content_ko,
            translated["title"], translated["content"],
            tags, image_url
        )

        if success:
            return jsonify({"success": True, "message": "Published!"})
        else:
            return jsonify({"error": "GitHub publish failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/analyze-image", methods=["POST"])
def admin_analyze_image():
    """이미지를 분석하여 태그 생성 + Cloudinary 업로드"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not model:
        return jsonify({"error": "AI model not configured"}), 500

    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    image_file = request.files["image"]
    image_data = image_file.read()
    image_base64 = base64.b64encode(image_data).decode("utf-8")

    try:
        # Gemini Vision으로 이미지 분석
        image_part = {
            "mime_type": image_file.content_type,
            "data": image_base64
        }

        prompt = """이 이미지를 분석해서 스톡 이미지 사이트에 업로드할 때 사용할 태그를 생성해주세요.

태그 요구사항:
- 영어로 작성
- 10-15개의 태그
- 구체적이고 검색에 유용한 키워드
- 쉼표로 구분

JSON 형식으로 응답:
{"tags": ["tag1", "tag2", ...], "description": "이미지 설명 (한국어)"}"""

        response = model.generate_content([prompt, image_part])
        text = response.text.strip()

        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        result = json.loads(text.strip())

        # Cloudinary에 이미지 업로드
        upload_result = cloudinary.uploader.upload(
            f"data:{image_file.content_type};base64,{image_base64}",
            folder="cheer-factory",
            tags=result.get("tags", [])
        )
        result["image_url"] = upload_result.get("secure_url", "")

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/edit/<post_id>")
def admin_edit(post_id):
    """포스트 수정 페이지"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    # GitHub에서 포스트 가져오기
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{post_id}.txt"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return redirect(url_for("admin"))

    file_info = response.json()
    content_response = requests.get(file_info["download_url"])
    if content_response.status_code != 200:
        return redirect(url_for("admin"))

    title, content, tags, image_url = parse_post_content(content_response.text)

    return render_template("admin_edit.html",
                           post_id=post_id,
                           title=title,
                           content=content,
                           tags=",".join(tags),
                           image_url=image_url)

@app.route("/admin/update", methods=["POST"])
def admin_update():
    """포스트 업데이트 (한국어 수정 시 영문도 자동 번역)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    post_id = data.get("post_id", "")
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", "")
    image_url = data.get("image_url", "")

    if not post_id or not title:
        return jsonify({"error": "Post ID and title required"}), 400

    # post_id에서 base_id 추출 (-ko, -en 제거)
    if post_id.endswith("-ko") or post_id.endswith("-en"):
        base_id = post_id[:-3]
    else:
        base_id = post_id

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 1. 먼저 영어 번역 시도 (실패하면 업데이트 중단)
    try:
        translated = translate_to_english(title, content)
        title_en = translated.get("title", title)
        content_en = translated.get("content", content)
    except Exception as e:
        return jsonify({"error": f"Translation failed: {str(e)}"}), 500

    # 2. 한국어 버전 업데이트
    file_content_ko = f"{title}\n"
    if tags:
        file_content_ko += f"TAGS: {tags}\n"
    if image_url:
        file_content_ko += f"IMAGE: {image_url}\n"
    file_content_ko += f"\n{content}"

    url_ko = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{base_id}-ko.txt"
    response_ko = requests.get(url_ko, headers=headers)
    if response_ko.status_code != 200:
        return jsonify({"error": "Post not found"}), 404

    sha_ko = response_ko.json().get("sha")
    content_base64_ko = base64.b64encode(file_content_ko.encode("utf-8")).decode("utf-8")

    update_ko = requests.put(url_ko, headers=headers, json={
        "message": f"Update post (KO): {title}",
        "content": content_base64_ko,
        "sha": sha_ko,
        "branch": "master"
    })

    if update_ko.status_code not in [200, 201]:
        error_msg = update_ko.json().get("message", "Unknown error")
        return jsonify({"error": f"KO update failed: {error_msg}"}), 500

    # 3. 영어 버전 업데이트
    file_content_en = f"{title_en}\n"
    if tags:
        file_content_en += f"TAGS: {tags}\n"
    if image_url:
        file_content_en += f"IMAGE: {image_url}\n"
    file_content_en += f"\n{content_en}"

    url_en = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{base_id}-en.txt"
    response_en = requests.get(url_en, headers=headers)

    content_base64_en = base64.b64encode(file_content_en.encode("utf-8")).decode("utf-8")

    if response_en.status_code == 200:
        # 기존 영문 파일 업데이트
        sha_en = response_en.json().get("sha")
        requests.put(url_en, headers=headers, json={
            "message": f"Update post (EN): {title_en}",
            "content": content_base64_en,
            "sha": sha_en,
            "branch": "master"
        })
    else:
        # 영문 파일이 없으면 새로 생성
        requests.put(url_en, headers=headers, json={
            "message": f"Add post (EN): {title_en}",
            "content": content_base64_en,
            "branch": "master"
        })

    # index.json 업데이트
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    date = "-".join(base_id.split("-")[:3]) if "-" in base_id else base_id

    update_post_in_index(f"{base_id}-ko", {
        "title": title,
        "content": content,
        "tags": tags_list,
        "image_url": image_url,
        "date": date
    })
    update_post_in_index(f"{base_id}-en", {
        "title": title_en,
        "content": content_en,
        "tags": tags_list,
        "image_url": image_url,
        "date": date
    })

    return jsonify({"success": True, "message": "Updated (KO + EN)"})

@app.route("/admin/delete", methods=["POST"])
def admin_delete():
    """포스트 삭제"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    post_id = data.get("post_id", "")

    if not post_id:
        return jsonify({"error": "Post ID required"}), 400

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 한국어/영어 버전 모두 삭제
    deleted = []
    errors = []

    for suffix in ["-ko", "-en"]:
        # post_id가 이미 -ko나 -en으로 끝나면 base_id 추출
        if post_id.endswith("-ko") or post_id.endswith("-en"):
            base_id = post_id[:-3]
        else:
            base_id = post_id

        file_id = f"{base_id}{suffix}"
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{file_id}.txt"

        # SHA 가져오기
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            continue

        sha = response.json().get("sha")

        # 파일 삭제
        delete_response = requests.delete(url, headers=headers, json={
            "message": f"Delete post: {file_id}",
            "sha": sha,
            "branch": "master"
        })

        if delete_response.status_code in [200, 204]:
            deleted.append(file_id)
            # index.json에서도 삭제
            remove_post_from_index(file_id)
        else:
            errors.append(file_id)

    if deleted:
        return jsonify({"success": True, "message": f"Deleted: {', '.join(deleted)}"})
    else:
        return jsonify({"error": "Failed to delete posts"}), 500

def translate_query_to_english(query):
    """한국어 검색어를 영어로 번역"""
    if not model:
        return query

    # 영어만 있으면 그대로 반환
    if query.isascii():
        return query

    try:
        prompt = f"""다음 검색어를 영어로 번역해주세요. 번역 결과만 출력하세요.
검색어: {query}"""
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return query

@app.route("/admin/generate-image", methods=["POST"])
def admin_generate_image():
    """AI로 이미지 생성 후 Cloudinary에 업로드"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not image_model:
        return jsonify({"error": "Image generation model not configured"}), 500

    data = request.json
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", "")

    if not title and not content:
        return jsonify({"error": "Title or content required"}), 400

    try:
        # 이미지 생성을 위한 프롬프트 생성
        prompt_text = f"""Create a warm, encouraging illustration for a blog post.

Title: {title}
Content summary: {content[:200] if len(content) > 200 else content}
Tags: {tags}

Style requirements:
- Warm and comforting color palette (soft oranges, warm yellows, gentle blues)
- Simple, clean illustration style
- Suitable for a motivational/encouraging blog
- No text in the image
- Horizontal landscape orientation (16:9 ratio)
- Professional yet friendly aesthetic"""

        # Gemini로 이미지 생성
        response = image_model.generate_content(prompt_text)

        # 이미지 데이터 추출
        image_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data.mime_type.startswith('image/'):
                image_data = part.inline_data.data
                break

        if not image_data:
            return jsonify({"error": "Failed to generate image"}), 500

        # Cloudinary에 업로드
        upload_result = cloudinary.uploader.upload(
            f"data:image/png;base64,{base64.b64encode(image_data).decode('utf-8')}",
            folder="cheer-factory/generated",
            resource_type="image"
        )

        return jsonify({
            "success": True,
            "image_url": upload_result.get("secure_url", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/search-images", methods=["POST"])
def admin_search_images():
    """Pexels에서 이미지 검색"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    if not PEXELS_API_KEY:
        return jsonify({"error": "Pexels API key not configured"}), 500

    data = request.json
    query = data.get("query", "")
    page = data.get("page", 1)

    if not query:
        return jsonify({"error": "Search query required"}), 400

    # 한국어를 영어로 번역
    translated_query = translate_query_to_english(query)

    try:
        url = "https://api.pexels.com/v1/search"
        params = {
            "query": translated_query,
            "per_page": 12,
            "page": page,
            "orientation": "landscape"
        }
        headers = {
            "Authorization": PEXELS_API_KEY
        }

        response = requests.get(url, params=params, headers=headers)

        if response.status_code != 200:
            return jsonify({"error": f"Pexels API error: {response.status_code}"}), 500

        data = response.json()
        images = []

        for photo in data.get("photos", []):
            images.append({
                "id": photo["id"],
                "thumb": photo["src"]["small"],
                "regular": photo["src"]["large"],
                "photographer": photo["photographer"],
                "photographer_url": photo["photographer_url"]
            })

        return jsonify({
            "images": images,
            "total_results": data.get("total_results", 0),
            "page": page,
            "translated_query": translated_query if translated_query != query else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/download-image", methods=["POST"])
def admin_download_image():
    """Pexels 이미지 다운로드 및 Cloudinary 업로드"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    image_url = data.get("image_url", "")

    if not image_url:
        return jsonify({"error": "Image URL required"}), 400

    try:
        # Cloudinary에 URL로 직접 업로드
        upload_result = cloudinary.uploader.upload(
            image_url,
            folder="cheer-factory"
        )

        return jsonify({
            "success": True,
            "image_url": upload_result.get("secure_url", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
