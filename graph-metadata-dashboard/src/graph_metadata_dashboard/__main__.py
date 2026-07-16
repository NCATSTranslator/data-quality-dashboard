from graph_metadata_dashboard.app import create_app
from graph_metadata_dashboard.config import Settings


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings)
    app.run(host="0.0.0.0", port=settings.port, debug=settings.debug)


if __name__ == "__main__":
    main()
