"""서브커맨드 라우팅."""
from __future__ import annotations

import argparse

from .config import load_config
from .logging_setup import get_logger

log = get_logger()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blog-automation", description="네이버 블로그 자동화")
    sub = parser.add_subparsers(dest="command", required=False)

    # collect: 과거 글 수집 (requests 기반, 로그인 불필요)
    c = sub.add_parser("collect", help="네이버 과거 글 수집(페르소나 학습용)")
    c.add_argument("--id", required=True,
                   help="블로그 주소 아이디(로그인 ID 아님! 예: cloudy43_)")
    c.add_argument("--max", type=int, default=None, help="최대 수집 글 수 override")

    # fetch: 구글 드라이브 사진/설명 다운로드
    f = sub.add_parser("fetch", help="구글 드라이브 공유링크에서 사진/설명 다운로드")
    f.add_argument("--url", required=True, help="구글 드라이브 공개 공유 링크")
    f.add_argument("--job", required=True, help="작업명(예: 맛집_240608)")

    # fetch-doc: Google Docs → 여러 포스트 일괄 다운로드
    fd = sub.add_parser("fetch-doc", help="Google Docs URL에서 포스트 목록 파싱 + 사진 일괄 다운로드")
    fd.add_argument("--url", required=True, help="Google Docs 공개 공유 링크")

    # video-scan: 영상에서 분석용 프레임 추출(토큰 절약 전처리)
    vs = sub.add_parser("video-scan",
                        help="photos/ 영상에서 분석용 프레임 추출(Claude 가 구간 선정용)")
    vs.add_argument("--job", required=True, help="작업명")

    # video-render: video_plan.json 대로 구간을 GIF 로 렌더
    vr = sub.add_parser("video-render",
                        help="video_plan.json 의 구간을 GIF 로 렌더 → photos/_gifs/")
    vr.add_argument("--job", required=True, help="작업명")

    # publish: 네이버 새 글 작성/발행
    p = sub.add_parser("publish", help="초고+배치도를 네이버 새 글에 작성")
    p.add_argument("--job", required=True, help="작업명")
    p.add_argument("--dry-run", action="store_true", help="입력만 하고 저장/발행 버튼은 누르지 않음")
    p.add_argument("--yes", "-y", action="store_true", help="미리보기 확인 프롬프트 생략")

    # engage: 자동 답방(품앗이) — ⚠️ 약관상 제재 위험, 보수적 사용
    e = sub.add_parser("engage", help="자동 답방: 댓글 단 사람 글 방문/체류/댓글")
    esub = e.add_subparsers(dest="engage_cmd", required=True)
    es = esub.add_parser("scan", help="댓글 단 사람 + 최근 글 수집 → targets.json")
    es.add_argument("--post", required=True, help="내 글 logNo 또는 전체 URL")
    es.add_argument("--job", required=True, help="작업명(예: 답방_240608)")
    er = esub.add_parser("run", help="대상 글 방문/체류(2분+)/댓글 등록")
    er.add_argument("--job", required=True, help="작업명")
    er.add_argument("--go", action="store_true",
                    help="실제 댓글 등록(미지정 시 dry-run: 체류만)")

    # ── SEO / Blog Growth (선택 레이어 — 기존 파이프라인 '앞단'. 기본 동작은 그대로) ──
    sub.add_parser("seo-init-db", help="blog_growth SQLite DB 초기화")

    si = sub.add_parser("seo-import-posts",
                        help="수집된 과거글(data/collected/<id>)을 growth DB(posts) 에 적재")
    si.add_argument("--id", required=True, help="블로그 주소 아이디(예: cloudy43_)")

    sr = sub.add_parser("seo-research-keywords",
                        help="입력 job 의 키워드 후보 조사(네이버 Open API/크롤링 폴백)")
    sr.add_argument("--job", required=True, help="작업명")

    sg = sub.add_parser("seo-generate-brief",
                        help="SEO 전략 브리프(data/drafts/<job>/SEO_BRIEF.md·SEO_REPORT.md) 생성")
    sg.add_argument("--job", required=True, help="작업명")

    sq = sub.add_parser("seo-quality-check",
                        help="작성된 post.md 를 brief 기준으로 기계 품질검사")
    sq.add_argument("--job", required=True, help="작업명")

    co = sub.add_parser("collect-outcomes", help="발행 후 성과 회수(post_outcomes 갱신)")
    co.add_argument("--days", type=int, default=7, help="회수 기준 일수(보통 1/3/7/30)")
    co.add_argument("--blog-id", default=None, help="블로그 주소 아이디 override(미지정 시 settings)")

    # app: 데스크톱 앱 실행/포커스 (인자 없이 main.py 실행해도 이게 돈다)
    sub.add_parser("app", help="데스크톱 앱(Voiceprint Studio) 실행/포커스")

    # inspect-dom: 자가치유용 라이브 DOM 조회(앱 안 네이버 화면에 CDP 로 붙어 셀렉터 진단)
    idom = sub.add_parser("inspect-dom",
                          help="라이브 DOM 조회(셀렉터 자가치유) — 어느 셀렉터가 깨졌는지/대체 후보 확인")
    idom.add_argument("--selector", default=None, help="이 셀렉터의 매칭 수/상세")
    idom.add_argument("--text", default=None, help="이 텍스트를 가진 보이는 요소 찾기(예: 발행)")
    idom.add_argument("--list", dest="list_kind", default=None,
                      help="요소 나열: buttons|inputs|editable|links|interactive(또는 임의 CSS)")
    idom.add_argument("--html", default=None, help="이 셀렉터 첫 매칭의 outerHTML")
    idom.add_argument("--section", default=None, help="건강검진 섹션 한정(기본: write,login)")
    idom.add_argument("--editor", action="store_true", help="먼저 에디터(postwrite)로 이동 후 검진")
    idom.add_argument("--goto", default=None, help="먼저 이 URL 로 이동 후 검진")
    idom.add_argument("--blog-id", default=None, help="블로그 주소 아이디 override")

    args = parser.parse_args(argv)
    if not args.command or args.command == "app":
        # 인자 없이 실행 = 데스크톱 앱 실행/포커스 (CLI 도움말은 python main.py -h).
        from .tools.launch_app import run_app
        run_app()
        return 0
    cfg = load_config()

    if args.command == "collect":
        from .collector.post_collector import run_collect
        run_collect(cfg, blog_id=args.id, max_posts=args.max)
    elif args.command == "fetch":
        from .drive.downloader import run_fetch
        run_fetch(cfg, url=args.url, job=args.job)
    elif args.command == "fetch-doc":
        from .drive.downloader import run_fetch_from_doc
        run_fetch_from_doc(cfg, doc_url=args.url)
    elif args.command == "video-scan":
        from .video.prep import run_video_scan
        run_video_scan(cfg, job=args.job)
    elif args.command == "video-render":
        from .video.prep import run_video_render
        run_video_render(cfg, job=args.job)
    elif args.command == "publish":
        from .publisher.naver_editor import run_publish
        run_publish(cfg, job=args.job, dry_run=args.dry_run, yes=args.yes)
    elif args.command == "engage":
        if args.engage_cmd == "scan":
            from .engage.scanner import run_scan
            run_scan(cfg, post=args.post, job=args.job)
        elif args.engage_cmd == "run":
            from .engage.commenter import run_engage
            run_engage(cfg, job=args.job, go=args.go)
    # ── SEO / Blog Growth (lazy import: leaf 모듈 문제가 기존 커맨드에 영향 주지 않게) ──
    elif args.command == "seo-init-db":
        from .seo.pipeline import run_init_db
        run_init_db()
    elif args.command == "seo-import-posts":
        from .seo.config import load_growth_config
        from .seo.pipeline import run_import_posts
        run_import_posts(cfg, load_growth_config(), blog_id=args.id)
    elif args.command == "seo-research-keywords":
        from .seo.config import load_growth_config
        from .seo.pipeline import run_research_keywords
        run_research_keywords(cfg, load_growth_config(), job=args.job)
    elif args.command == "seo-generate-brief":
        from .seo.config import load_growth_config
        from .seo.pipeline import run_generate_brief
        run_generate_brief(cfg, load_growth_config(), job=args.job)
    elif args.command == "seo-quality-check":
        from .seo.config import load_growth_config
        from .seo.pipeline import run_quality_check
        run_quality_check(cfg, load_growth_config(), job=args.job)
    elif args.command == "collect-outcomes":
        from .seo.config import load_growth_config
        from .seo.outcome_tracker import collect_outcomes
        collect_outcomes(cfg, load_growth_config(), days=args.days, blog_id=args.blog_id)
    elif args.command == "inspect-dom":
        from .tools.inspect_dom import run_inspect_dom
        run_inspect_dom(cfg, selector=args.selector, text=args.text, list_kind=args.list_kind,
                        html=args.html, section=args.section, editor=args.editor,
                        goto=args.goto, blog_id=args.blog_id)
    return 0
