"""서브커맨드 라우팅."""
from __future__ import annotations

import argparse

from .config import load_config
from .logging_setup import get_logger

log = get_logger()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blog-automation", description="네이버 블로그 자동화")
    sub = parser.add_subparsers(dest="command", required=True)

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

    args = parser.parse_args(argv)
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
    return 0
