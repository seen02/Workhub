"""Publish a verified local package, retaining the previous release and source guides."""
import argparse, hashlib, json, pathlib, re, shutil, subprocess, sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def passed_tests(path):
    text=path.read_text(encoding='utf-8-sig');numbers=re.findall(r'Ran (\d+) tests',text)
    if not numbers or not re.search(r'\nOK\s*$',text):raise RuntimeError('Regression result is not successful')
    return int(numbers[-1])
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[0-9]{8}-[0-9]+',args.version):raise ValueError('Invalid version')
    stage=ROOT/('deployment-next-'+args.version);current=ROOT/'deployment'
    release=read(stage/'release.json');old_version=read(current/'release.json')['version']
    if release['version']!=args.version or not re.fullmatch(r'[0-9]{8}-[0-9]+',old_version):raise ValueError('Version mismatch')
    archive=ROOT/'deployment-archive'/old_version
    for path in (stage,current,archive):
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():raise ValueError('Release path must stay within the workspace')
    if archive.exists():raise RuntimeError('Previous release archive already exists; preserve it')
    for path,key in [('source-audit.json','passed'),('reports/release-start-smoke.json','passed'),('reports/preservation.json','passed'),('reports/inventory-restored.json','matches_backup_inventory')]:
        if read(stage/path).get(key) is not True:raise RuntimeError('Release verification gate failed: '+path)
    runtime_tests=passed_tests(stage/'reports/workhub-tests.txt');development_tests=passed_tests(stage/'reports/development-workhub-tests.txt')
    if runtime_tests!=436 or development_tests!=436:raise RuntimeError('Unexpected regression test count')
    image_manifest=read(stage/'artifacts'/('workhub-images-'+args.version+'.tar.manifest.json'))
    if image_manifest['images']!=release['images']:raise RuntimeError('Image archive and release versions differ')
    backup=ROOT/'backups'/('release-refresh-'+args.version);backup.mkdir(parents=True,exist_ok=True)
    for source,name in [(ROOT.parent/'docs/local/OVERVIEW.md','project-README.md'),(ROOT.parent/'docs/local/OVERVIEW.md','workspace-README.md'),(ROOT.parent/'docs/local/integrations/outline/README.md','outline-integration-README.md')]:
        target=backup/name
        if not target.exists():shutil.copy2(source,target)

    text=(current/'README.md').read_text(encoding='utf-8').replace(old_version,args.version)
    text=text.replace('최근 Workhub UI/일정/담당자 필터/조회 최적화, Nginx HTTP 임시 주소, 현재 계정·문서·업무·채팅·RAG·모델 데이터를 포함합니다.',
        '2026-10-07 현재 실행본의 프로젝트 관리·진행 통계·새 업무 등록·칸반·자료 검색·내 업무 조회·보고 초안 개선과 현재 계정·문서·업무·채팅·RAG·모델 데이터를 포함합니다.')
    text=text.replace('- `source-manifest.json`, `source-audit.json`, `reports`: 소스 해시 및 검증 결과',
        '- `artifacts/workhub-development-'+args.version+'.zip`: 실제 설정·데이터를 제외한 최신 개발 소스·테스트·Outline 원본 및 패치·개발 빌드 안내\n'
        '- `source-manifest.json`, `source-audit.json`, `checksums.json`, `reports`: 소스·배포 파일 해시와 검증 결과')
    text+='\n## 개발본과 이전 배포본\n\n개발 ZIP을 별도 폴더에 풀면 `development/README.md`에서 코드 수정과 개발 이미지 빌드·테스트 절차를 확인할 수 있습니다. 회사 서버의 첫 기동은 위 배포 절차를 사용합니다. 개발 ZIP과 실행 배포본은 같은 '+args.version+' 기준입니다.\n\n이전 '+old_version+' 배포본은 `../deployment-archive/'+old_version+'/`에 원본 그대로 보존했습니다. 기존 서버에 새 데이터가 쌓인 뒤 과거 백업을 덮어써서 돌아가는 방법은 사용하지 않습니다.\n'
    (stage/'README.md').write_text(text,encoding='utf-8')

    text=(ROOT.parent/'docs/local/OVERVIEW.md').read_text(encoding='utf-8')
    text=text.replace('배포 상태는 2026-09-28 기준입니다.','개발 소스·실행 이미지·배포 묶음은 **20261007-1** 기준으로 정리했습니다. 코드 인계는 [개발본 안내](development/README.md), 서버 전달은 배포 폴더를 사용합니다.')
    text=text.replace('| 배포 묶음의 설치·복원·포함 버전 |','| 최신 개발본·고정 이미지·개발 빌드 | [개발본 안내](development/README.md) · [개발 버전](development/version.json) |\n| 배포 묶음의 설치·복원·포함 버전 |')
    text=text.replace('3. 관리자가 **Workhub**에서 업무와 완료 기준을 만들고 담당자를 배정합니다. 업무 문서는 해당 컬렉션의 최상위 **업무 목록** 아래에 저장됩니다.',
        '3. **Outline**의 최상위 **업무 목록**에서 **＋ 새 업무**로 업무를 등록합니다. 관리자는 완료 기준과 담당자를 지정하고, 일반 직원은 본인 업무를 등록합니다. 칸반과 진행 통계도 Outline에서 사용합니다.')
    text=text.replace('여러 업무를 한 번에 보고하면 AI가 업무명·완료 기준별 통합 초안을 제시합니다.',
        '여러 업무를 한 번에 보고하면 업무명·완료 기준별 통합 초안을 제시합니다. 명확한 보고는 직접 해석하고 모호한 표현은 기존 검색·AI 경로로 확인합니다.')
    text=text.replace('`deployment/`는 **20260928-1**, 이전 버전은 `deployment-archive/20260922-1/` 및 `20260921-1/`에 보관했습니다.',
        '`deployment/`는 **20261007-1**입니다. 이전 버전은 `deployment-archive/20260928-1/`, `20260922-1/`, `20260921-1/`에 보관했습니다.')
    text=text.replace('2026-09-29 보고 개편은 로컬 소스·실행 컨테이너에 반영했습니다. 위 20260928-1 배포 묶음에는 아직 포함하지 않았습니다.',
        '2026-10-07까지 적용한 프로젝트 관리·진행 통계·새 업무 등록·칸반·검색·내 업무 조회·보고 초안 개선을 최신 개발 ZIP과 배포 묶음에 포함했습니다.')
    text=text.replace('Nginx HTTP 임시 주소, 최근 Workhub 화면·일정·조회 최적화 및 현재 데이터는 배포본 **20260928-1**에 포함했습니다.',
        '현재 실행 이미지 16개와 데이터 저장소 14개를 보존한 배포본 **20261007-1**을 별도 저장소에 복원·기동해 검증했습니다. 최신 Workhub 테스트 436개와 배포 도구 테스트 9개를 통과했습니다.')
    (ROOT.parent/'docs/local/OVERVIEW.md').write_text(text,encoding='utf-8')
    text=(ROOT.parent/'docs/local/OVERVIEW.md').read_text(encoding='utf-8')
    text=text.replace('2026-09-22 정리.','2026-10-07 개발·배포 버전 갱신. 2026-09-22 문서 정리 이력은 아래에 유지한다.')
    text=text.replace('최신 **20260928-1** 배포 패키지: 이미지·데이터 백업·설정·설치 도구','최신 **20261007-1** 배포 패키지: 이미지·데이터 백업·설정·설치 도구·개발 소스 ZIP')
    text=text.replace('이전 **20260922-1**, **20260921-1** 배포본 보관','이전 **20260928-1**, **20260922-1**, **20260921-1** 배포본 보관')
    text=text.replace('[팀 협업 시연과 초기화](unified-work-assistant/TEAM-DEMO-GUIDE.md)','[내 업무 조회 시연](unified-work-assistant/내_업무_시연_가이드.md)')
    text=text.replace('|`src/workhub`|','|[development](unified-work-assistant/development/README.md)|20261007-1 개발 소스 기준과 고정 이미지에서 개발 빌드·테스트하는 방법|\n|`src/workhub`|',1)
    (ROOT.parent/'docs/local/OVERVIEW.md').write_text(text,encoding='utf-8')
    path=ROOT.parent/'docs/local/integrations/outline/README.md';text=path.read_text(encoding='utf-8')
    text=text.replace('# Outline 프로젝트 관리 통합\n','# Outline 프로젝트 관리 통합\n\n2026-10-07 개발·배포 기준은 **20261007-1**이다. 최신 패치는 공식 원본 대비 44개 파일 재현 검증을 통과했으며 현재 Outline 실행 이미지와 함께 배포 묶음에 포함했다. 개발 빌드는 [개발본 안내](../../development/README.md), 서버 설치는 [배포 안내](../../deployment/README.md)를 사용한다.\n',1)
    text=text.replace('현재 로컬 이미지는 Outline `kanban-first-drop-20261006`, Workhub `kanban-reset-20261006`',
        '현재 로컬 이미지는 Outline `kanban-first-drop-20261006`, Workhub `report-fastpath-20261007`')
    path.write_text(text,encoding='utf-8')
    report=f'''# 최신 개발본·배포본 정리 — {args.version}

2026-10-07 개발 작업 트리·현재 실행 이미지·서버 전달용 배포 묶음을 같은 버전으로 정리했다. 회사 서버에 적용한 결과가 아니라 로컬에서 복원·기동까지 검증한 배포 준비본이다.

## 포함한 최신 변경

- Outline 프로젝트 등록·책임자·연결 해제·재연결과 권한 검사.
- Outline 진행 통계, 담당자·프로젝트 조회 조건과 관리자·직원 구분.
- 새 업무 간편 등록, 날짜 입력·달력, 사이드바 등록과 연속 등록.
- 칸반 완료 기준·상태·초기화, 새 탭 탐색과 카드 드롭 판정 개선.
- 자료 검색·채팅 검색과 접근 권한, 최신 색인 갱신.
- 채팅 내 업무·기한 초과·완료 기준 조회와 계정·담당자 동기화.
- 보고 개편·오인식 수정·요청 내 조회 재사용과 2026-10-07 명확한 보고 초안 개선.
- 현재 계정·문서·업무·채팅·초안·RAG 색인·AI 모델 데이터, Nginx HTTP 임시 주소 5개와 기존 리소스 제한.

보고 업무 목록 사전 갱신, AI 입력·출력 축소, 제출 대기 분리 등 미착수 기능은 구현 완료로 표시하지 않는다. 단계별 상태는 개발 소스의 보고 성능 및 신뢰성 개선 명세를 따른다.

## 개발본

- `artifacts/workhub-development-{args.version}.zip`: 현재 작업 트리의 소스·테스트·의존성·운영 문서·배포 도구와 Outline 공식 원본/패치.
- 개발용 Dockerfile은 이번 배포 태그에서 시작한다. 로컬 Workhub 개발 이미지 `workhub-dev/workhub:{args.version}`도 만들고 **436개 테스트 통과**를 확인했다.
- Git 초기 커밋과 현재 미커밋 변경을 구분하여 `development/version.json`과 `source-manifest.json`에 기록한다. Git 초기화·커밋·푸시는 하지 않았다.
- 실제 인증 설정·데이터·인증서·캐시·빌드 산출물은 개발 ZIP에서 제외했다. DB에 설치되는 WebUI 도구는 소스와 별도로 설치 위치별 해시를 검사했다.

## 배포본과 검증

- Linux amd64 실행 이미지 **16개**와 일관된 데이터 저장소 **14개**를 포함한다. 이미지 아카이브는 약 {image_manifest['bytes']/1024**3:.2f} GiB다.
- Workhub 실행 파일 81개, 문서 비서 Dockerfile에 지정된 파일 49개, 임베딩 워커 3개, WebUI 도구/필터 5개, Outline 서버 연동 소스 10개가 현재 개발 소스와 일치했다.
- 새 `test_report_fastpath.py`는 개발 전용 테스트 파일로 개발 ZIP·개발 이미지에 포함했다. 현재 서비스에 필요한 실제 코드의 불일치는 없다.
- Outline 공식 원본 SHA-256과 관리 패치 **44개 파일** 재현 검증을 통과했다. 프런트는 기존 검증된 실행 이미지를 정확한 digest로 고정했으며 이번 정리에서 재빌드하거나 동작을 바꾸지 않았다.
- 배포 관리 도구 안전성 테스트 **9개 통과**. 격리된 배포 실행본의 최신 Workhub 테스트도 **436개 통과**.
- `{read(stage/'reports/release-start-smoke.json')['project']}`에 별도 저장소로 복원하여 16개 서비스의 건강 상태, SSO discovery, 봇 연결, 공개 프록시의 내부 API 차단을 확인했다.
- Outline·Authentik·Workhub·WebUI·문서 비서·Rocket.Chat·RAG의 주요 레코드 수가 원본 스냅샷과 같았다. Workhub 로그인 세션·인증 사본은 기존 복원 원칙대로 초기화하여 새 로그인을 요구한다.
- 원래 16개 컨테이너의 ID·이미지·마운트를 보존했고 모두 다시 실행했다. 검증본은 별도 데이터 저장소를 사용했고 검증 후 중지했다. 기존 데이터나 과거 배포본은 삭제하지 않았다.
- `checksums.json`, 이미지·개발 ZIP의 manifest 및 `artifacts/source-baseline/manifest.json`에 파일 체크섬을 기록했다.

## 버전과 실행 상태

| 구분 | 현재 기준 |
|---|---|
| 개발 소스·배포 묶음 | {args.version} |
| 로컬 Workhub | unified-work-assistant/workhub:report-fastpath-20261007 |
| 로컬 Outline | unified-work-assistant/outline:kanban-first-drop-20261006 |
| 로컬 문서 비서 | unified-work-assistant/document-agent:search-20260930 |
| 이전 배포본 | ../deployment-archive/{old_version}/ — 원본 보존 |
| 설치·복원·실행 | [README.md](README.md) |

검증 환경은 Windows Docker Desktop의 Linux amd64 컨테이너다. 실제 Ubuntu 서버 설치, 회사 서버 배포와 대규모 동시 AI 부하 검증은 수행하지 않았다. 실제 서버 주소·HTTPS·SMTP·백업 예약은 서버 환경에서 정해야 한다.

## 검증 자료와 복구

- [현재 실행 코드 대조](source-audit.json), [소스 해시](source-manifest.json), [배포 파일 체크섬](checksums.json).
- [별도 복원본 기동](reports/release-start-smoke.json), [복원 레코드 비교](reports/inventory-restored.json), [복원본 코드 대조](reports/restored-source-audit.json).
- [개발 이미지 테스트](reports/development-workhub-tests.txt), [배포본 최신 코드 테스트](reports/workhub-tests.txt), [원래 서비스·데이터 분리 보존](reports/preservation.json).
- 이전 배포 폴더는 `../deployment-archive/{old_version}/`, 수정 전 안내 문서는 `../backups/release-refresh-{args.version}/`에 보존했다. 패키지 선택을 되돌릴 때 이전 묶음을 사용하고 운영 데이터에 과거 백업을 덮어쓰지 않는다.
'''
    (stage/'PREPARATION_REPORT.md').write_text(report,encoding='utf-8')
    subprocess.run([sys.executable,str(ROOT/'ops/package_development_release.py'),'--version',args.version],check=True)
    release=read(stage/'release.json')
    checksums={}
    for path in stage.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.tar','.zip'):continue
        checksums[path.relative_to(stage).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    checksums['artifacts/'+image_manifest['file']]=image_manifest['sha256']
    dev=release['development_source'];checksums['artifacts/'+dev['file']]=dev['sha256']
    baseline=read(stage/'artifacts/source-baseline/manifest.json')
    checksums.update({'artifacts/source-baseline/'+value['file']:value['sha256'] for value in baseline['volumes'].values()})
    write(stage/'checksums.json',{'version':args.version,'algorithm':'SHA-256','files':checksums})
    archive.parent.mkdir(exist_ok=True)
    current.rename(archive)
    try:stage.rename(current)
    except BaseException:
        archive.rename(current);raise
    print(json.dumps({'passed':True,'version':args.version,'development_files':dev['files'],'development_zip_bytes':dev['bytes'],'image_archive_bytes':image_manifest['bytes'],'data_volumes':len(baseline['volumes']),'previous_release_preserved':old_version,'latest_directory':str(current)},ensure_ascii=False))
if __name__=='__main__':main()
