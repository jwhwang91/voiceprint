"""콘솔 + 파일 로거.

콘솔(StreamHandler)과 함께 `<logs>/blog_automation.log` 에도 기록한다(logs 위치는 `paths`
가 결정 — 개발 모드는 repo 루트 logs/, 앱 모드는 <workspace>/logs/). 파일 핸들러는 UTF-8 이라
한글이 깨지지 않으며([GROUP_CHOOSER_DUMP] 같은 진단 로그를 다음 실행에서 그대로 읽어 분석 가능).

⚠️ 모듈 import 시점에 `log = get_logger()` 를 호출하는 곳이 많아, CLI `--workspace` 가
   파싱되기 전에 파일 핸들러가 만들어질 수 있다. 그래서 `refresh_file_handler()` 로 logs 위치를
   다시 잡을 수 있게 한다(cli 가 --workspace 적용 직후 호출). 앱 모드(env)는 import 시점에
   이미 env 가 있으므로 처음부터 올바른 위치로 간다.
"""
import logging

from . import paths


def _add_file_handler(logger: logging.Logger) -> None:
    try:
        log_dir = paths.get_logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh = logging.FileHandler(log_dir / "blog_automation.log", encoding="utf-8")
        fh.setFormatter(file_fmt)
        fh._voiceprint_file = True  # type: ignore[attr-defined]  # refresh 가 식별하려고 표식
        logger.addHandler(fh)
    except Exception:  # noqa: BLE001 — 파일 핸들러 실패해도 콘솔 로깅은 유지
        pass


def get_logger(name: str = "blog_automation") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
        console = logging.StreamHandler()
        console.setFormatter(console_fmt)
        logger.addHandler(console)
        _add_file_handler(logger)
        logger.setLevel(logging.INFO)
    return logger


def refresh_file_handler(name: str = "blog_automation") -> None:
    """logs 위치가 바뀌었을 때(예: CLI --workspace) 파일 핸들러를 새 위치로 다시 건다."""
    logger = logging.getLogger(name)
    for h in list(logger.handlers):
        if getattr(h, "_voiceprint_file", False):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
    _add_file_handler(logger)
