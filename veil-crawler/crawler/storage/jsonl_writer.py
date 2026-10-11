"""UTF-8 JSONL 파일에 한 게시물을 한 줄씩 기록합니다."""
import json
from dataclasses import asdict
from pathlib import Path

from models.post import Post


class JsonlWriter:
    def __init__(self, path: Path, exclusive=False):
        self.path = Path(path)
        self.exclusive = exclusive
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("x" if self.exclusive else "w", encoding="utf-8", newline="\n")
        return self

    def write(self, post: Post):
        line = json.dumps(asdict(post), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self.file.write(line + "\n")
        self.file.flush()

    def __exit__(self, exc_type, exc_value, traceback):
        if self.file:
            self.file.close()
