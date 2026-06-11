"""AutomateBlogWriting CLI 진입점.

사용 예:
    python main.py collect  --id <네이버ID> [--manual-login]
    python main.py fetch    --url <드라이브 공유링크> --job <작업명>
    python main.py publish  --job <작업명> [--dry-run]

분석/작성(2,4단계)은 Claude Code가 prompts/ 지시서를 따라 수행합니다. CLAUDE.md 참고.
"""
import sys
from pathlib import Path

# src/ 를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent / "src"))

from blog_automation.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
