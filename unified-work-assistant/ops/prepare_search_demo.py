"""Idempotent, clearly marked demo references; never changes task documents."""
import json
from workhub import outline

REFERENCES={
 '[검색 시연] 고객 포털 요구사항':'''# 고객 포털 요구사항

이 문서는 자료 검색 기능을 확인하기 위한 시연용 자료입니다. 실제 운영 요구사항이 아닙니다.

## 배포 전 승인 조건

고객 포털 배포 전에는 팀장이 요구사항 범위와 승인 여부를 확인해야 합니다.

김철수는 로그인, 문의 등록, 처리 상태 조회 화면이 요구사항대로 동작하는지 검증하고 결과를 남깁니다.

홍길동은 사용자 안내 문서를 준비합니다. 김철수는 배포 후 점검 절차를 준비합니다.

고객 포털은 로그인한 사용자가 자신의 문의와 처리 상태만 조회할 수 있어야 합니다. 다른 사용자의 문의가 노출되면 배포를 보류합니다.

## 이번 배포에서 제외하는 기능

모바일 앱과 결제 기능은 이번 고객 포털 배포 범위에 포함되지 않습니다.
''',
 '[검색 시연] 고객 포털 배포 체크리스트':'''# 고객 포털 배포 체크리스트

이 문서는 자료 검색 기능을 확인하기 위한 시연용 자료입니다. 실제 운영 체크리스트가 아닙니다.

## 배포 전에 확인할 항목

배포 전 팀장은 요구사항 승인 기록과 화면 검증 결과를 확인합니다.

김철수는 로그인 실패 시 안내 메시지와 재시도 동작을 확인합니다. 문의 등록 후 처리 상태가 갱신되는지도 점검합니다.

김철수는 배포 직전 데이터 백업과 이전 버전 복구 절차를 확인합니다. 운영 환경의 설정값과 서비스 연결 상태도 점검합니다.

## 배포 후 확인할 항목

배포 후에는 로그인, 문의 등록, 처리 상태 조회를 순서대로 확인하고 오류 기록을 점검합니다.

시연 자료 점검표 식별자는 DEMO-RELEASE-0921입니다.
''',
 '[검색 시연] 고객 포털 협업 회의록':'''# 고객 포털 협업 회의록

이 문서는 자료 검색 기능을 확인하기 위한 시연용 회의록입니다. 실제 회의 결정이 아닙니다.

## 결정 사항

고객 포털의 요구사항 승인은 팀장, 요구사항 정리와 사용자 안내는 홍길동, 화면 검증과 배포 점검 준비는 김철수가 담당합니다.

화면 검증 결과와 배포 점검 준비가 확인된 후 팀장이 배포 여부를 결정합니다.

배포 일자와 예산은 이 회의에서 확정하지 않았습니다.
'''
}

def main():
    results=[]
    for p in outline.projects():
        if p['name'] not in ('팀 협업 시연','시연 · 고객 포털'):continue
        docs=outline.all_items('documents.list',{'collectionId':p['id']})
        for title,text in REFERENCES.items():
            found=next((d for d in docs if d['title']==title),None)
            if found:
                doc=outline.api('documents.info',{'id':found['id']})
                if '시연용' not in doc.get('text',''):raise RuntimeError('기존 문서는 덮어쓰지 않습니다.')
                if ''.join(doc['text'].split())==''.join(text.split()):pass
                else:
                    outline.api('documents.update',{'id':doc['id'],'text':text,'lastRevision':doc['revision']})
            else:doc=outline.api('documents.create',{'collectionId':p['id'],'title':title,'text':text,'publish':True})
            results.append({'project':p['name'],'collection_id':p['id'],'id':doc['id'],'title':title,'created':found is None})
    print(json.dumps(results,ensure_ascii=False))
if __name__=='__main__':main()
