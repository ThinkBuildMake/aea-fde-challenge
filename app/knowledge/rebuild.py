"""The rebuildIndex command: python -m app.knowledge.rebuild"""

import json
import sys

from app.errors import AppError
from app.knowledge.embeddings import Embedder
from app.knowledge.service import rebuild_index
from app.main import create_app
from app.settings import load_settings_or_exit


def main(embedder: Embedder | None = None) -> int:
    settings = load_settings_or_exit()
    settings.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    ctx = create_app(settings, embedder=embedder).state.ctx
    try:
        result = rebuild_index(ctx)
    except AppError as error:
        sys.stderr.write(
            json.dumps({"error": error.code, "message": error.message}) + "\n"
        )
        return 1
    sys.stdout.write(json.dumps(result.model_dump(by_alias=True)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
