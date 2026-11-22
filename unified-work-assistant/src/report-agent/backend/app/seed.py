import json
import hashlib
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Employee, Project, Report, Task


def seed_database(db: Session) -> None:
    if db.scalar(select(func.count(Employee.id))):
        return

    employees = [
        Employee(name="김진성", team="공간정보팀"),
        Employee(name="이서연", team="품질인증팀"),
        Employee(name="박민수", team="콘텐츠팀"),
        Employee(name="최지훈", team="AI전략팀"),
        Employee(name="정수빈", team="공간정보팀"),
    ]
    projects = [
        Project(name="도로명 컨설팅", status="IN_PROGRESS", expected_progress=78),
        Project(name="SP 인증 준비", status="IN_PROGRESS", expected_progress=68),
        Project(name="철도연 시연영상", status="DELAYED", expected_progress=65),
        Project(name="AI Agent 기술 조사", status="IN_PROGRESS", expected_progress=90),
    ]
    db.add_all([*employees, *projects])
    db.flush()

    employee = {item.name: item for item in employees}
    project = {item.name: item for item in projects}
    today = date.today()

    tasks = [
        Task(project=project["도로명 컨설팅"], employee=employee["김진성"], title="PostGIS 공간질의 자료조사", status="IN_PROGRESS", progress=50, expected_progress=65, started_at=today - timedelta(days=5), due_date=today + timedelta(days=3)),
        Task(project=project["도로명 컨설팅"], employee=employee["정수빈"], title="도로명 데이터 품질 점검", status="IN_PROGRESS", progress=82, expected_progress=78, started_at=today - timedelta(days=7), due_date=today + timedelta(days=2)),
        Task(project=project["도로명 컨설팅"], employee=employee["최지훈"], title="공간 API 적용성 검토", status="DONE", progress=100, expected_progress=100, started_at=today - timedelta(days=9), due_date=today),
        Task(project=project["SP 인증 준비"], employee=employee["이서연"], title="SP 인증 문서 작성", status="IN_PROGRESS", progress=65, expected_progress=68, started_at=today - timedelta(days=8), due_date=today + timedelta(days=5)),
        Task(project=project["SP 인증 준비"], employee=employee["정수빈"], title="인증 증빙자료 정리", status="IN_PROGRESS", progress=72, expected_progress=65, started_at=today - timedelta(days=6), due_date=today + timedelta(days=5)),
        Task(project=project["철도연 시연영상"], employee=employee["박민수"], title="철도연 영상 캡처", status="DELAYED", progress=40, expected_progress=65, started_at=today - timedelta(days=8), due_date=today + timedelta(days=1)),
        Task(project=project["철도연 시연영상"], employee=employee["이서연"], title="시연 자막 검수", status="IN_PROGRESS", progress=55, expected_progress=60, started_at=today - timedelta(days=4), due_date=today + timedelta(days=2)),
        Task(project=project["AI Agent 기술 조사"], employee=employee["최지훈"], title="AI Agent 프레임워크 조사", status="IN_PROGRESS", progress=95, expected_progress=90, started_at=today - timedelta(days=10), due_date=today + timedelta(days=1)),
        Task(project=project["AI Agent 기술 조사"], employee=employee["김진성"], title="LLM Provider 비교", status="DONE", progress=100, expected_progress=100, started_at=today - timedelta(days=7), due_date=today),
    ]
    db.add_all(tasks)
    db.flush()

    task = {item.title: item for item in tasks}
    samples = [
        ("김진성", "PostGIS 공간질의 자료조사", "09:00~12:00 PostGIS 공간질의 유형을 정리했습니다. 3개 중 1개 완료, 이슈는 없습니다.", 3, 33, None, "나머지 질의 정리", 8, 45),
        ("김진성", "LLM Provider 비교", "13:00~15:00 Mock과 Local LLM Provider 비교를 완료했습니다. 이슈 없음.", 2, 100, None, "결과 공유", 15, 10),
        ("이서연", "SP 인증 문서 작성", "09:00~14:00 SP 인증 문서 20개 항목 중 13개를 작성했습니다.", 5, 65, None, "자체 점검", 14, 20),
        ("박민수", "철도연 영상 캡처", "09:00~12:00 시연영상 캡처를 진행했습니다. 영상 화질 문제로 재작업이 필요합니다.", 3, 40, "영상 화질 문제로 재작업 발생", "영상 재캡처", 13, 50),
        ("최지훈", "AI Agent 프레임워크 조사", "09:00~15:00 AI Agent 프레임워크 20개 중 19개 조사를 완료했습니다.", 6, 95, None, "결과 보고", 12, 35),
        ("정수빈", "도로명 데이터 품질 점검", "10:00~14:00 도로명 데이터 품질 점검 11개 중 9개 완료했습니다.", 4, 82, None, "오류 데이터 보정", 11, 5),
        ("박민수", "철도연 영상 캡처", "14:00~16:00 영상 재캡처를 진행했으나 화질 문제가 계속됩니다.", 2, 40, "영상 화질 문제로 재작업 발생", "장비 설정 확인", 16, 15),
        ("이서연", "시연 자막 검수", "15:00~17:00 자막 20개 중 11개 검수를 완료했습니다.", 2, 55, None, "나머지 자막 검수", 17, 10),
        ("정수빈", "인증 증빙자료 정리", "14:00~17:00 인증 증빙자료 18개 중 13개 정리했습니다.", 3, 72, None, "누락 자료 요청", 16, 40),
        ("최지훈", "공간 API 적용성 검토", "공간 API 적용성 검토를 완료하고 결과를 공유했습니다.", 2, 100, None, None, 10, 30),
        ("이서연", "SP 인증 문서 작성", "인증 문서 목차와 담당자를 확정했습니다. 전체 진행률 45%입니다.", 3, 45, None, "본문 작성", 9, 20),
        ("박민수", "철도연 영상 캡처", "촬영 구간 10개 중 4개를 캡처했습니다. 장비 설정 오류가 있었습니다.", 3, 40, "장비 설정 오류", "화질 테스트", 9, 5),
        ("김진성", "PostGIS 공간질의 자료조사", "공간질의 예제를 수집했습니다. 3개 중 1개를 정리했습니다.", 2, 33, None, "성능 비교", 8, 30),
        ("정수빈", "도로명 데이터 품질 점검", "검증 규칙 5개 중 4개 적용했습니다.", 4, 80, None, "결과 샘플링", 8, 10),
        ("최지훈", "AI Agent 프레임워크 조사", "후보 프레임워크 장단점을 비교했습니다. 진행률 85%입니다.", 5, 85, None, "최종 권고안", 7, 55),
        ("이서연", "시연 자막 검수", "자막 초안을 전달받아 검수 기준을 세웠습니다. 진행률 30%입니다.", 2, 30, None, "1차 검수", 7, 20),
        ("김진성", "LLM Provider 비교", "Provider 인터페이스 초안을 완료했습니다.", 3, 100, None, "통합 테스트", 6, 50),
    ]

    for idx, (employee_name, task_title, raw, duration, progress, issue, next_action, hour, minute) in enumerate(samples):
        created_day = today if idx < 10 else today - timedelta(days=1)
        summary = {
            "employee": employee_name,
            "task": task_title,
            "status": task[task_title].status,
            "progress": progress,
            "issue": issue,
            "next_action": next_action,
        }
        db.add(
            Report(
                employee=employee[employee_name],
                task=task[task_title],
                raw_message=raw,
                structured_summary=json.dumps(summary, ensure_ascii=False),
                duration_hours=duration,
                progress=progress,
                issue=issue,
                next_action=next_action,
                fingerprint=hashlib.sha256(
                    f"{employee[employee_name].id}:{task[task_title].project_id}:{created_day}:{' '.join(raw.lower().split())}".encode("utf-8")
                ).hexdigest(),
                created_at=datetime.combine(created_day, time(hour, minute)),
                updated_at=datetime.combine(created_day, time(hour, minute)),
            )
        )
    db.commit()
