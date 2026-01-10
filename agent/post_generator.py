"""
Cheer Factory 글 생성 에이전트
Google AI (Gemini)를 사용하여 익명 블로그 스타일의 글을 생성하고
GitHub API를 통해 직접 배포합니다.
"""

import json
import os
import base64
from datetime import datetime
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv
import requests

load_dotenv()

# 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "chad0920kim/cheer-factory")

# Gemini 설정
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

SYSTEM_PROMPT = """당신은 'Cheer Factory'라는 익명 블로그의 작가입니다.

## 글쓰기 스타일
- 따뜻하고 진정성 있는 톤
- 짧고 간결한 문장 (3-5문장 정도의 단락)
- 독자에게 용기와 위로를 주는 내용
- 일상의 작은 깨달음이나 생각을 담담하게 표현
- 이모지 사용 금지
- 존댓말 사용

## 형식
- 제목: 짧고 인상적인 한 줄 (15자 이내)
- 본문: 2-4개의 짧은 단락
- 마지막은 독자에게 건네는 한마디로 마무리

## 주제 예시
- 작은 성취의 가치
- 쉬어가는 것의 중요성
- 실패해도 괜찮다는 위로
- 일상 속 감사할 것들
- 자기 자신을 돌보는 법
"""


def generate_post(topic: str = None) -> dict:
    """
    AI를 사용하여 블로그 글을 생성합니다.

    Args:
        topic: 글의 주제 (선택사항). 없으면 AI가 자유롭게 선택

    Returns:
        생성된 포스트 딕셔너리 {"title": str, "content": str}
    """
    if topic:
        user_prompt = f"다음 주제로 글을 작성해주세요: {topic}"
    else:
        user_prompt = "오늘의 글을 자유롭게 작성해주세요."

    prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}\n\nJSON 형식으로 응답해주세요:\n{{\"title\": \"제목\", \"content\": \"본문\"}}"

    response = model.generate_content(prompt)
    text = response.text.strip()

    # JSON 파싱
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    return json.loads(text.strip())


def get_existing_posts_count(date: str) -> int:
    """GitHub에서 해당 날짜의 기존 포스트 수를 확인합니다."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return 0

    files = response.json()
    count = sum(1 for f in files if f["name"].startswith(date))
    return count


def publish_to_github(title: str, content: str) -> dict:
    """
    GitHub API를 통해 직접 포스트를 생성하고 커밋합니다.

    Returns:
        {"success": bool, "filename": str, "url": str}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    post_num = get_existing_posts_count(today) + 1
    filename = f"{today}-{post_num:03d}.json"

    post_data = {
        "title": title,
        "date": today,
        "content": content,
        "likes": 0
    }

    # JSON을 base64로 인코딩
    content_json = json.dumps(post_data, ensure_ascii=False, indent=2)
    content_base64 = base64.b64encode(content_json.encode("utf-8")).decode("utf-8")

    # GitHub API로 파일 생성
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "message": f"Add post: {title}",
        "content": content_base64,
        "branch": "master"
    }

    response = requests.put(url, headers=headers, json=data)

    if response.status_code in [200, 201]:
        return {
            "success": True,
            "filename": filename,
            "url": f"https://github.com/{GITHUB_REPO}/blob/master/posts/{filename}"
        }
    else:
        return {
            "success": False,
            "error": response.json().get("message", "Unknown error"),
            "status_code": response.status_code
        }


def create_and_publish_post(topic: str = None) -> dict:
    """
    글을 생성하고 GitHub에 바로 배포합니다.

    Args:
        topic: 글의 주제 (선택사항)

    Returns:
        {"title": str, "content": str, "filename": str, "url": str, "success": bool}
    """
    post = generate_post(topic)
    result = publish_to_github(post["title"], post["content"])

    return {
        "title": post["title"],
        "content": post["content"],
        **result
    }


if __name__ == "__main__":
    import sys

    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

    print("글을 생성하고 GitHub에 배포합니다...")
    result = create_and_publish_post(topic)

    if result.get("success"):
        print(f"\n✓ 글이 배포되었습니다!")
        print(f"제목: {result['title']}")
        print(f"파일: {result['filename']}")
        print(f"URL: {result['url']}")
        print(f"\n--- 내용 ---\n{result['content']}")
    else:
        print(f"\n✗ 배포 실패: {result.get('error')}")
