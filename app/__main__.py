import os

from app.settings import load_settings_or_exit
from app.startup import run_startup


def main() -> None:
    settings = load_settings_or_exit()
    run_startup(settings)

    import uvicorn

    from app.llm import OpenRouterProvider
    from app.main import create_app

    uvicorn.run(
        create_app(settings, model=OpenRouterProvider(settings)),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
