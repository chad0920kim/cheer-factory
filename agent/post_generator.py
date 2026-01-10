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

## 페르소나
- 10년 넘게 인사담당자로 일해온 40대 후반 남성
- 수많은 사람들의 입사와 퇴사, 성장과 좌절을 곁에서 지켜봐온 경험
- 최근 바이브코딩에 빠져 새로운 도전을 즐기는 중
- 인생의 굴곡을 겪어본 사람 특유의 깊이와 여유가 있음

## 글쓰기 스타일
- 부드럽지만 핵심을 찌르는 톤
- 설교하지 않고, 경험에서 우러나온 이야기로 자연스럽게 교훈을 전달
- 직장생활, 인간관계, 자기계발에 대한 현실적인 통찰
- "~하세요"보다는 "~더라고요", "~것 같습니다" 같은 공유하는 느낌
- 짧고 간결한 문장 (3-5문장 정도의 단락)
- 이모지 사용 금지
- 존댓말 사용

## 형식
- 제목: 짧고 인상적인 한 줄 (15자 이내)
- 본문: 2-4개의 짧은 단락
- 마지막은 독자에게 건네는 따뜻한 한마디로 마무리

## 주제 예시
- 면접에서 보이는 사람의 본질
- 실패해도 다시 일어서는 법
- 나이 들어 새로운 것을 배운다는 것
- 조직에서 살아남는 진짜 능력
- 퇴사를 고민하는 후배에게
- 작은 성취가 쌓여 만드는 변화
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


def translate_to_english(title: str, content: str) -> dict:
    """
    한국어 글을 영어로 번역합니다.

    Returns:
        {"title": str, "content": str}
    """
    prompt = f"""다음 한국어 블로그 글을 영어로 자연스럽게 번역해주세요.
원문의 따뜻하고 진정성 있는 톤을 유지하면서, 영어권 독자에게도 공감이 가도록 번역해주세요.

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


def get_existing_posts_count(date: str) -> int:
    """GitHub에서 해당 날짜의 기존 포스트 수를 확인합니다."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return 0

    files = response.json()
    count = sum(1 for f in files if f["name"].startswith(date) and f["name"].endswith(".txt"))
    return count


def publish_file_to_github(filename: str, file_content: str, commit_message: str) -> dict:
    """
    GitHub API를 통해 파일을 생성하고 커밋합니다.

    Returns:
        {"success": bool, "filename": str, "url": str}
    """
    content_base64 = base64.b64encode(file_content.encode("utf-8")).decode("utf-8")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/posts/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "message": commit_message,
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


def publish_to_github(title_ko: str, content_ko: str, title_en: str, content_en: str) -> dict:
    """
    한국어와 영어 포스트를 GitHub에 배포합니다.

    Returns:
        {"success": bool, "filename_ko": str, "filename_en": str, "url_ko": str, "url_en": str}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    post_num = get_existing_posts_count(today) + 1

    # 한국어 파일
    filename_ko = f"{today}-{post_num:03d}-ko.txt"
    file_content_ko = f"{title_ko}\n\n{content_ko}"
    result_ko = publish_file_to_github(filename_ko, file_content_ko, f"Add post (KO): {title_ko}")

    if not result_ko["success"]:
        return result_ko

    # 영어 파일
    filename_en = f"{today}-{post_num:03d}-en.txt"
    file_content_en = f"{title_en}\n\n{content_en}"
    result_en = publish_file_to_github(filename_en, file_content_en, f"Add post (EN): {title_en}")

    return {
        "success": result_ko["success"] and result_en["success"],
        "filename_ko": filename_ko,
        "filename_en": filename_en,
        "url_ko": result_ko.get("url"),
        "url_en": result_en.get("url"),
        "error": result_en.get("error") if not result_en["success"] else None
    }


def create_and_publish_post(topic: str = None) -> dict:
    """
    글을 생성하고 한국어/영어 버전을 GitHub에 배포합니다.

    Args:
        topic: 글의 주제 (선택사항)

    Returns:
        {"title_ko": str, "content_ko": str, "title_en": str, "content_en": str, ...}
    """
    # 한국어 글 생성
    post_ko = generate_post(topic)

    # 영어로 번역
    post_en = translate_to_english(post_ko["title"], post_ko["content"])

    # 배포
    result = publish_to_github(
        post_ko["title"], post_ko["content"],
        post_en["title"], post_en["content"]
    )

    return {
        "title_ko": post_ko["title"],
        "content_ko": post_ko["content"],
        "title_en": post_en["title"],
        "content_en": post_en["content"],
        **result
    }


if __name__ == "__main__":
    import sys

    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

    print("글을 생성하고 GitHub에 배포합니다...")
    result = create_and_publish_post(topic)

    if result.get("success"):
        print(f"\n✓ 글이 배포되었습니다!")
        print(f"\n[한국어]")
        print(f"제목: {result['title_ko']}")
        print(f"파일: {result['filename_ko']}")
        print(f"\n[English]")
        print(f"Title: {result['title_en']}")
        print(f"File: {result['filename_en']}")
        print(f"\n--- 한국어 내용 ---\n{result['content_ko']}")
        print(f"\n--- English Content ---\n{result['content_en']}")
    else:
        print(f"\n✗ 배포 실패: {result.get('error')}")
