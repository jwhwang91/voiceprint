"""콘솔 + 파일 로거.

콘솔(StreamHandler)과 함께 ROOT/logs/blog_automation.log 에도 기록한다.
파일 핸들러는 UTF-8 이라 한글이 깨지지 않으며(콘솔 cp949 mojibake 회피),
[GROUP_CHOOSER_DUMP] 같은 진단 로그를 다음 실행에서 그대로 읽어 분석할 수 있다.
"""
import logging
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_FILE = _LOG_DIR / "blog_automation.log"


def get_logger(name: str = "blog_automation") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
        console = logging.StreamHandler()
        console.setFormatter(console_fmt)
        logger.addHandler(console)

        # 파일 핸들러(UTF-8). 실패해도 콘솔 로깅은 유지.
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
            file_handler.setFormatter(file_fmt)
            logger.addHandler(file_handler)
        except Exception:  # noqa: BLE001
            pass

        logger.setLevel(logging.INFO)
    return logger
