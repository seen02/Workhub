from datetime import datetime, timezone
from app.rocketchat.report_format import format_report


def test_company_report_groups_and_restarts_numbering():
    items=[
        {"project":"ai-assistant","task":"환경 구성 및 연동","status":"DONE","progress":100},
        {"project":"ai-assistant","task":"작성·확정·조회 테스트","status":"IN_PROGRESS","progress":60},
        {"project":"ai-assistant","task":"이전 보고 가져오기 및 RAG 도입","status":"NOT_STARTED","progress":0},
        {"project":"spatial-agent","task":"검색 품질 개선","status":"IN_PROGRESS","progress":30},
        {"project":"spatial-agent","task":"검색 테스트","status":"IN_PROGRESS","progress":50},
    ]
    text=format_report(items,datetime(2026,9,9,9))
    assert text.startswith("**[업무목록]**\n- 로켓챗 기반 업무 비서 AI Agent 개발\n- 자연어 기반 GIS 분석 프로젝트 진행 방향 정리")
    assert "[9월 9일 수요일 : 9시]" in text
    assert "1. 환경 구성 및 연동(✅ 완료)" in text
    assert "2. 작성·확정·조회 테스트(🔄 진행중 60%)" in text
    assert "3. 이전 보고 가져오기 및 RAG 도입(⏳ 예정)" in text
    assert "1. 검색 품질 개선(🔄 진행중 30%)" in text
    assert "2. 검색 테스트(🔄 진행중 50%)" in text
    assert "100%" not in text and "미기재" not in text


def test_empty_and_unknown_progress_and_kst_date():
    text=format_report([{"task":"미선택 업무","status":"IN_PROGRESS","progress":None}],datetime(2026,9,8,15,5,tzinfo=timezone.utc))
    assert "[9월 9일 수요일 : 0시 5분]" in text
    assert "프로젝트 미선택" in text and "미선택 업무(🔄 진행중)" in text
    assert "%" not in text


def test_format_does_not_allow_mentions_or_injected_headings():
    text=format_report([{"project":"ai-assistant","task":"@all\n**가짜 제목**","status":"DONE"}],datetime(2026,9,9,9))
    assert "@all" not in text and "\n**가짜 제목**" not in text
