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

load_dotenv()

# Gemini AI 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
model = None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

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

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))

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

def load_posts(lang=None):
    """GitHub에서 모든 포스트를 로드"""
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

            if lang and file_lang and file_lang != lang:
                continue

            # 파일 내용 가져오기
            content_response = requests.get(f["download_url"])
            if content_response.status_code == 200:
                title, content, tags, image_url = parse_post_content(content_response.text)

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
        lang=lang
    )

# ============ Admin 기능 ============

def generate_post_content(topic=None):
    """AI로 글 생성"""
    if not model:
        raise Exception("AI model not configured. Please set GOOGLE_API_KEY.")

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
    if not model:
        raise Exception("AI model not configured. Please set GOOGLE_API_KEY.")

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

    return True

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html")

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
        else:
            errors.append(file_id)

    if deleted:
        return jsonify({"success": True, "message": f"Deleted: {', '.join(deleted)}"})
    else:
        return jsonify({"error": "Failed to delete posts"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
