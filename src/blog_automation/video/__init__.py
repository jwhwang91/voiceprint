"""영상(MOV/MP4) → GIF 전처리.

분업(CLAUDE.md 철학과 동일):
  · Python(기계): 토큰 안 드는 프레임 추출(scan) + ffmpeg GIF 렌더(render).
  · Claude(인지): scan 이 뽑은 작은 썸네일만 보고 '쓸 영상 / 자를 구간'을 정해
    data/drafts/<job>/video_plan.json 에 적고, 결과 GIF 를 layout.json image 블록에 배치.

GIF 는 .gif 라 기존 사진 업로드 경로(image_uploader)를 그대로 타므로 발행 코드 수정이 없다.
"""
from .prep import run_video_scan, run_video_render, VIDEO_EXTS

__all__ = ["run_video_scan", "run_video_render", "VIDEO_EXTS"]
