"""영상 → 분석용 프레임 추출(scan) + 구간 → GIF 렌더(render).

두 개의 사용자 실행 커맨드를 제공한다(Python = 기계적 작업):
  · run_video_scan   : photos/ 하위 모든 영상에서 토큰-저렴한 썸네일 프레임을 뽑아
                       data/drafts/<job>/video/ 에 저장 + videos.json 매니페스트 작성.
  · run_video_render : Claude 가 작성한 data/drafts/<job>/video_plan.json 의 구간을
                       ffmpeg(palettegen 2-pass)으로 GIF 로 렌더 → photos/_gifs/ 에 저장.

중간 단계(어느 영상을 쓸지, 어디서 어디까지 자를지)는 Claude 가 scan 산출물을 보고
판단해 video_plan.json 을 채운다. prompts/write_post.md §0.5 참고.

설계 불변식:
  1) 영상 원본을 비전 모델에 통으로 넣지 않는다 — 항상 다운스케일 프레임만(토큰 상한 고정).
  2) ffmpeg/ffprobe 부재·디코드 실패는 '그 영상만 건너뛰고' 전체를 멈추지 않는다.
  3) iPhone 회전 메타데이터(rotation)는 ffmpeg 자동회전(기본 on)에 맡긴다 — 프레임/GIF 가
     화면에 보이는 방향대로 나온다(별도 transpose 금지).
  4) GIF 는 네이버 1장 10MB 한도 아래(_GIF_MAX_BYTES)로 자동 축소(fps→폭→길이 순).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import Config
from ..logging_setup import get_logger
from ..utils.files import read_json, write_json

log = get_logger()

# photos/ 하위에서 영상으로 인식할 확장자
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"}

# --- scan(분석용 프레임 추출) 튜닝 ---------------------------------------------
_FRAME_SCALE = 480        # 분석 썸네일 가로폭(px) — 작을수록 토큰 절약(흐름 파악엔 충분)
_SAMPLE_DENSITY = 1.2     # 짧은 영상: 초당 약 1.2 프레임 샘플
_MIN_FRAMES = 3
_MAX_FRAMES = 8           # 영상당 프레임 상한(토큰 캡) — 길이와 무관하게 고정

# --- 모션 기반 프레임 선택 -----------------------------------------------------
# 균일 분할 대신 '움직임이 큰 구간'에 분석 프레임을 몰아준다(GIF 목적엔 움직이는 순간이 핵심).
# 전부 ffmpeg/CPU 계산이라 토큰 0. n개 시간 bin 으로 나눠 각 bin 의 최대-모션 프레임을 고름(스프레드+모션).
_MOTION_FPS = 10          # 모션 에너지 곡선 샘플레이트(곡선 해상도; 디코드는 전체 프레임)
_MOTION_SCALE = 160       # 모션 계산용 초저해상도(빠름; 실제 추출 프레임 화질과 무관)
_MOTION_TIMEOUT = 90      # 모션 분석 ffmpeg 타임아웃(초) — 초과 시 균일 샘플로 폴백
_MOTION_MAX_SEC = 180.0   # 이보다 길면 모션 분석(전체 디코드)이 비싸 생략 — 균일 샘플만(행 방지)

# --- render(GIF) 기본값/한도 --------------------------------------------------
# 네이버 한도는 10MB지만, 모바일 로딩/체감을 위해 6MB 를 목표 상한으로 둔다(움짤은 가볍게).
_GIF_MAX_BYTES = 6 * 1024 * 1024
_DEFAULT_FPS = 12
_DEFAULT_WIDTH = 480      # 세로 영상(4K 폰)도 무난한 폭. 가로 영상은 plan 에서 540~600 가능.
_MAX_DURATION = 4.0       # GIF 1개 최대 길이(초) — 용량/체감 모두 고려
# 용량 초과 시 시도하는 (fps, width) 축소 사다리(앞에서부터 적용). 움직임 많은 컷 대비 폭까지 단계적↓.
_SHRINK_LADDER = ((12, 480), (10, 480), (10, 400), (10, 360), (8, 360), (8, 320))


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe 래퍼
# ---------------------------------------------------------------------------

def _require_ffmpeg() -> None:
    """ffmpeg/ffprobe 가 PATH 에 있어야 한다(없으면 친절히 멈춤)."""
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise SystemExit(
            f"'{', '.join(missing)}' 를 찾을 수 없습니다. 설치 후 다시 실행하세요 "
            f"(macOS: `brew install ffmpeg`).")


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """ffmpeg/ffprobe 실행. stdin 을 닫아(비대화형에서 멈추지 않게) + 선택적 타임아웃.

    타임아웃 초과 시 returncode=124 의 빈 결과를 돌려줘 호출부가 폴백하게 한다(행 방지)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg/ffprobe 시간 초과(%ss) — 건너뜀: %s", timeout, " ".join(cmd[:4]))
        return subprocess.CompletedProcess(cmd, 124, "", "")


def _parse_fraction(text: str) -> float:
    """'30000/1001' 같은 프레임레이트 문자열 → float."""
    text = (text or "").strip()
    if not text or text in ("0/0", "N/A"):
        return 0.0
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _probe(path: Path) -> dict[str, Any]:
    """영상 메타데이터(길이/해상도/fps/회전)를 ffprobe 로 읽는다(실패 시 빈 dict)."""
    cp = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "format=duration:stream=width,height,avg_frame_rate:"
        "stream_tags=rotate:side_data=rotation",
        "-of", "json", str(path),
    ])
    if cp.returncode != 0:
        log.warning("ffprobe 실패(건너뜀): %s — %s", path.name, cp.stderr.strip()[:200])
        return {}
    try:
        data = json.loads(cp.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    fps = _parse_fraction(stream.get("avg_frame_rate", ""))
    # 회전: side_data(rotation) 또는 tags.rotate
    rotation = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rotation = int(sd["rotation"])
            except (TypeError, ValueError):
                pass
    if not rotation:
        try:
            rotation = int((stream.get("tags") or {}).get("rotate") or 0)
        except (TypeError, ValueError):
            rotation = 0
    # ffmpeg 자동회전이 화면 방향대로 디코드하므로, 표시 해상도는 회전 시 가로/세로를 바꾼다.
    disp_w, disp_h = (height, width) if rotation in (90, -90, 270, -270) else (width, height)
    return {
        "duration": round(duration, 3),
        "width": disp_w, "height": disp_h,
        "fps": round(fps, 3), "rotation": rotation,
    }


# ---------------------------------------------------------------------------
# scan: 분석용 프레임 추출
# ---------------------------------------------------------------------------

def _sample_timestamps(duration: float) -> list[float]:
    """영상 길이에 비례한 균일 샘플 타임스탬프(양 끝 살짝 안쪽). 토큰 상한(_MAX_FRAMES) 적용."""
    if duration <= 0:
        return [0.0]
    n = round(duration * _SAMPLE_DENSITY)
    n = max(_MIN_FRAMES, min(_MAX_FRAMES, n))
    step = duration / (n + 1)
    return [round(step * (i + 1), 3) for i in range(n)]


def _motion_energy(src: Path) -> list[tuple[float, float]]:
    """프레임 간 차분(=움직임) 에너지 시계열 [(pts_time, energy), ...] 을 ffmpeg 로 계산(토큰 0).

    초저해상도로 다운스케일 후 tblend(차분)으로 '바뀐 양'을 만들고 signalstats 의 평균 밝기
    (YAVG)를 프레임별 모션 점수로 읽는다. 실패/타임아웃이면 빈 리스트 → 호출부가 균일로 폴백.
    """
    cp = _run([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(src),
        "-vf", (f"fps={_MOTION_FPS},scale={_MOTION_SCALE}:-1,tblend=all_mode=difference,"
                "signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=-"),
        "-an", "-f", "null", "-",
    ], timeout=_MOTION_TIMEOUT)
    if cp.returncode != 0:
        return []
    series: list[tuple[float, float]] = []
    cur_t: float | None = None
    for raw in cp.stdout.splitlines():
        s = raw.strip()
        if s.startswith("frame:"):
            cur_t = None
            for tok in s.split():
                if tok.startswith("pts_time:"):
                    try:
                        cur_t = float(tok.split(":", 1)[1])
                    except ValueError:
                        cur_t = None
        elif s.startswith("lavfi.signalstats.YAVG=") and cur_t is not None:
            try:
                series.append((cur_t, float(s.split("=", 1)[1])))
            except ValueError:
                pass
    return series


def _motion_timestamps(src: Path, duration: float, n: int) -> list[tuple[float, float]]:
    """모션 에너지가 높은 프레임 n장을 고른다. n개 시간 bin 으로 나눠 각 bin 의 최대-모션 프레임 선택.

    → 스프레드(시간 구간별 1장)와 모션 인식(그 구간에서 가장 움직이는 순간)을 동시에 만족.
    실패 시 빈 리스트.
    """
    series = _motion_energy(src)
    if not series:
        return []
    picks: list[tuple[float, float]] = []
    for b in range(n):
        lo, hi = duration * b / n, duration * (b + 1) / n
        bucket = [(t, e) for (t, e) in series if lo <= t < hi]
        if bucket:
            picks.append(max(bucket, key=lambda te: te[1]))
    seen: set[float] = set()
    out: list[tuple[float, float]] = []
    for t, e in sorted(picks):
        rt = round(t, 3)
        if rt not in seen:
            seen.add(rt)
            out.append((rt, e))
    return out


def _select_timestamps(src: Path, duration: float) -> tuple[list[tuple[float, float | None]], str]:
    """분석 프레임 타임스탬프(최대 _MAX_FRAMES)를 고른다. 반환: ([(t, motion|None)], 모드).

    1순위 모션 기반(움직임 큰 구간 우선). 매우 길면(>_MOTION_MAX_SEC) 전체 디코드가 비싸 균일.
    모션 분석 실패/부족 시 균일 폴백. (어느 경우든 토큰 비용은 프레임 수 = 동일)
    """
    n = max(_MIN_FRAMES, min(_MAX_FRAMES, round(duration * _SAMPLE_DENSITY)))
    if duration > _MOTION_MAX_SEC:
        return [(t, None) for t in _sample_timestamps(duration)], "uniform-long(모션생략)"
    motion = _motion_timestamps(src, duration, n)
    if len(motion) >= _MIN_FRAMES:
        return [(t, e) for (t, e) in motion], "motion"
    return [(t, None) for t in _sample_timestamps(duration)], "uniform(모션폴백)"


def _extract_frame(src: Path, t: float, out_path: Path) -> bool:
    """타임스탬프 t(초)의 프레임 1장을 다운스케일 JPG 로 추출. -ss 를 -i 앞에 둬 빠른 키프레임 시크."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cp = _run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-ss", f"{t:.3f}", "-i", str(src),
        "-frames:v", "1",
        "-vf", f"scale={_FRAME_SCALE}:-1:flags=lanczos",
        "-q:v", "4", str(out_path),
    ])
    if cp.returncode != 0 or not out_path.exists():
        log.warning("프레임 추출 실패 t=%.2f %s — %s", t, src.name, cp.stderr.strip()[:160])
        return False
    return True


def _safe_key(rel: str) -> str:
    """'강아지들/IMG_0245.MOV' → '강아지들__IMG_0245' (프레임 폴더명/충돌 방지)."""
    p = Path(rel)
    return (str(p.parent).replace("/", "__") + "__" + p.stem).lstrip("_.").replace(" ", "_") \
        if str(p.parent) not in (".", "") else p.stem.replace(" ", "_")


def run_video_scan(cfg: Config, job: str) -> None:
    """photos/ 하위 모든 영상에서 분석용 프레임을 추출하고 매니페스트를 쓴다(사용자 실행).

    산출: data/drafts/<job>/video/frames/<key>/frame_XXX_tNN.NN.jpg
          data/drafts/<job>/video/videos.json
    """
    _require_ffmpeg()
    photos_dir = cfg.input_dir / job / "photos"
    if not photos_dir.is_dir():
        raise SystemExit(f"photos 폴더가 없습니다: {photos_dir}")

    videos = sorted(p for p in photos_dir.rglob("*")
                    if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    if not videos:
        log.info("영상 파일이 없습니다(%s). 사진만 있으면 이 단계는 건너뛰면 됩니다.", photos_dir)
        return

    out_root = cfg.drafts_dir / job / "video"
    frames_root = out_root / "frames"
    log.info("영상 %d개 발견 — 분석용 프레임 추출 시작(가로 %dpx, 영상당 최대 %d장)",
             len(videos), _FRAME_SCALE, _MAX_FRAMES)

    manifest: dict[str, Any] = {"job": job, "frame_scale": _FRAME_SCALE, "videos": []}
    seen_keys: dict[str, int] = {}   # _safe_key 충돌 시 프레임 폴더가 겹치지 않게 카운터 부여
    for src in videos:
        rel = str(src.relative_to(photos_dir))
        meta = _probe(src)
        duration = meta.get("duration", 0.0)
        if duration <= 0:
            log.warning("길이를 못 읽어 건너뜀: %s", rel)
            continue
        stamps, mode = _select_timestamps(src, duration)

        # 프레임 폴더 키를 run 안에서 유일하게(공백/구분자 충돌로 두 영상이 한 폴더를 공유하는 것 방지)
        base_key = _safe_key(rel)
        n = seen_keys.get(base_key, 0) + 1
        seen_keys[base_key] = n
        key = base_key if n == 1 else f"{base_key}_{n}"
        frame_dir = frames_root / key
        # 이전 실행 잔여 프레임 정리(구간/개수 바뀔 수 있음)
        if frame_dir.exists():
            shutil.rmtree(frame_dir, ignore_errors=True)

        frames: list[dict[str, Any]] = []
        for i, (t, energy) in enumerate(stamps):
            fname = f"frame_{i:03d}_t{t:05.2f}.jpg"
            if _extract_frame(src, t, frame_dir / fname):
                fr: dict[str, Any] = {"file": f"{key}/{fname}", "t": t}
                if energy is not None:
                    fr["motion"] = round(energy, 1)   # 높을수록 그 프레임 구간의 움직임이 큼(선택 힌트)
                frames.append(fr)
        if not frames:
            log.warning("추출된 프레임이 없어 건너뜀: %s", rel)
            continue

        manifest["videos"].append({
            "source": rel,
            "duration": duration,
            "width": meta.get("width", 0),
            "height": meta.get("height", 0),
            "fps": meta.get("fps", 0),
            "rotation": meta.get("rotation", 0),
            "sample_mode": mode,
            "frames": frames,
        })
        log.info("  %-40s %.1fs → %d프레임(%s)", rel, duration, len(frames), mode)

    out_root.mkdir(parents=True, exist_ok=True)
    write_json(out_root / "videos.json", manifest)
    log.info("프레임 추출 완료 → %s", frames_root)
    log.info("다음: Claude 가 frames/ 를 보고 data/drafts/%s/video_plan.json 을 작성 → "
             "`python main.py video-render --job \"%s\"`", job, job)


# ---------------------------------------------------------------------------
# render: 구간 → GIF
# ---------------------------------------------------------------------------

def _render_gif(src: Path, start: float, duration: float, fps: int, width: int,
                out_path: Path) -> int:
    """구간 [start, start+duration] 을 palettegen 2-pass 로 GIF 렌더. 반환: 바이트 크기(실패 0)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    palette = out_path.with_name(out_path.stem + ".palette.png")
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    # 1) 팔레트 생성(stats_mode=diff: 움직이는 영역 색을 우선해 화질↑)
    p1 = _run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
        "-vf", f"{vf},palettegen=stats_mode=diff", "-an", str(palette),
    ])
    if p1.returncode != 0 or not palette.exists():
        log.warning("팔레트 생성 실패: %s — %s", out_path.name, p1.stderr.strip()[:160])
        palette.unlink(missing_ok=True)   # 부분 생성된 팔레트 png 가 _gifs/ 에 남지 않게
        return 0
    # 2) 팔레트 적용(bayer 디더로 밴딩↓, 용량 적당)
    p2 = _run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
        "-i", str(palette),
        "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
        "-an", "-loop", "0", str(out_path),
    ])
    palette.unlink(missing_ok=True)
    if p2.returncode != 0 or not out_path.exists():
        log.warning("GIF 렌더 실패: %s — %s", out_path.name, p2.stderr.strip()[:160])
        return 0
    return out_path.stat().st_size


def _render_with_budget(src: Path, start: float, duration: float,
                        fps: int, width: int, out_path: Path) -> dict[str, Any]:
    """용량 한도(_GIF_MAX_BYTES) 안에 들 때까지 (fps, width) 를 단계적으로 낮춰 렌더."""
    if duration > _MAX_DURATION:
        log.info("  %s 요청 길이 %.1fs → 최대 %.1fs 로 제한", out_path.name, duration, _MAX_DURATION)
        duration = _MAX_DURATION
    # 요청값보다 큰 단계는 건너뛰고, 요청값 이하 단계만 시도(요청을 상한으로 존중)
    ladder = [(f, w) for (f, w) in _SHRINK_LADDER if f <= fps and w <= width]
    if not ladder:
        ladder = [(fps, width)]
    if (fps, width) not in ladder:
        ladder.insert(0, (fps, width))
    last = {"ok": False, "bytes": 0, "fps": fps, "width": width}
    for f, w in ladder:
        size = _render_gif(src, start, duration, f, w, out_path)
        last = {"ok": size > 0, "bytes": size, "fps": f, "width": w,
                "duration": round(duration, 3)}
        if 0 < size <= _GIF_MAX_BYTES:
            return last
        if size > _GIF_MAX_BYTES:
            log.info("  %s %.1fMB > 한도 — 축소 재시도(fps/폭↓)",
                     out_path.name, size / 1024 / 1024)
    if last["bytes"] > _GIF_MAX_BYTES:
        log.warning("  %s 가 한도(%.0fMB)를 넘습니다(%.1fMB). 구간을 줄이거나 폭을 낮추세요.",
                    out_path.name, _GIF_MAX_BYTES / 1024 / 1024, last["bytes"] / 1024 / 1024)
    if not last["ok"]:
        # 마지막 시도가 실패(0바이트)면, 이전 단계가 남긴 과대 GIF 가 디스크에 남지 않게 제거.
        out_path.unlink(missing_ok=True)
    return last


def run_video_render(cfg: Config, job: str) -> None:
    """video_plan.json 의 각 구간을 GIF 로 렌더해 photos/_gifs/ 에 저장(사용자 실행).

    입력: data/drafts/<job>/video_plan.json
      {
        "job": "...",
        "clips": [
          {"source": "강아지들/IMG_0245.MOV", "out": "IMG_0245.gif",
           "start": 1.2, "duration": 3.0, "fps": 12, "width": 540,
           "caption": "...", "category": "강아지들", "note": "꼬리 흔드는 구간"}
        ]
      }
    출력: data/input/<job>/photos/_gifs/<out>.gif  (발행이 사진처럼 픽업)
    """
    _require_ffmpeg()
    plan_path = cfg.drafts_dir / job / "video_plan.json"
    if not plan_path.is_file():
        raise SystemExit(
            f"video_plan.json 이 없습니다: {plan_path}\n"
            f"먼저 `python main.py video-scan --job \"{job}\"` 실행 후, "
            f"Claude 가 프레임을 보고 video_plan.json 을 작성해야 합니다.")
    plan = read_json(plan_path)
    clips = plan.get("clips", [])
    if not isinstance(clips, list):
        raise SystemExit("video_plan.json 의 'clips' 는 배열(JSON array)이어야 합니다.")
    if not clips:
        log.info("video_plan.json 에 clips 가 비어 있습니다 — 렌더할 GIF 없음.")
        return

    photos_dir = cfg.input_dir / job / "photos"
    gifs_dir = photos_dir / "_gifs"

    # 선처리: 각 clip 의 출력 파일명을 확정하고 중복을 막는다. 같은 out 은 디스크에서 서로
    # 덮어쓰고(ffmpeg -y) layout.json 도 파일명으로 구분을 못 하므로, 조용히 진행하지 말고 멈춘다.
    def _out_name(clip: dict, idx: int) -> str:
        rel = clip.get("source") or ""
        name = clip.get("out") or (Path(rel).stem + ".gif" if rel else f"clip_{idx}.gif")
        return name if name.lower().endswith(".gif") else name + ".gif"

    out_names = [_out_name(c if isinstance(c, dict) else {}, i) for i, c in enumerate(clips)]
    dups = sorted({n for n in out_names if out_names.count(n) > 1})
    if dups:
        detail = "; ".join(
            f"{n} ← clips {[i for i, x in enumerate(out_names) if x == n]}" for n in dups)
        raise SystemExit(
            "video_plan.json: 중복된 out 파일명이 있습니다 — " + detail + ". "
            "각 구간에 서로 다른 out 을 지정하세요(예: 같은 영상이면 IMG_0245_01.gif, IMG_0245_02.gif).")

    log.info("GIF 렌더 시작 — %d개 구간 → %s", len(clips), gifs_dir)

    ok, failed = 0, []
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            log.warning("clips[%d]: 객체가 아님 — 건너뜀", i); failed.append(i); continue
        rel = clip.get("source")
        if not rel:
            log.warning("clips[%d]: source 없음 — 건너뜀", i); failed.append(i); continue
        src = photos_dir / rel
        if not src.is_file():
            # 카테고리 폴더 없이 파일명만 준 경우 재귀 탐색(resolve 와 동일 정신)
            cand = sorted(photos_dir.rglob(Path(rel).name))
            src = cand[0] if cand else src
        if not src.is_file():
            log.warning("clips[%d]: 영상 파일 없음 → %s", i, rel); failed.append(i); continue

        out_name = out_names[i]
        out_path = gifs_dir / out_name

        try:
            start = float(clip.get("start", 0.0))
            duration = float(clip.get("duration", 3.0))
            fps = int(clip.get("fps", _DEFAULT_FPS))
            width = int(clip.get("width", _DEFAULT_WIDTH))
        except (TypeError, ValueError):
            log.warning("clips[%d]: start/duration/fps/width 가 숫자가 아님 — 건너뜀 (%s)", i, out_name)
            failed.append(i); continue

        res = _render_with_budget(src, start, duration, fps, width, out_path)
        if res["ok"]:
            ok += 1
            log.info("  ✓ %-22s ⟵ %s [%.1f~%.1fs] %dfps %dpx %.1fMB",
                     out_name, rel, start, start + res["duration"],
                     res["fps"], res["width"], res["bytes"] / 1024 / 1024)
        else:
            failed.append(i)
            log.error("  ✗ %s 렌더 실패 (source=%s)", out_name, rel)

    log.info("GIF 렌더 완료 — 성공 %d / 실패 %d → %s", ok, len(failed), gifs_dir)
    if ok:
        log.info("layout.json 에는 파일명만 적으면 됩니다(예: {\"type\":\"image\",\"file\":\"%s\"}). "
                 "발행(publish)은 photos/_gifs/ 까지 재귀로 찾습니다.",
                 (clips[0].get("out") or "clip.gif"))
