import argparse

from app.adapters.identity import FeishuProfile
from app.db.session import create_database_engine, create_session_factory
from app.modules.identity_access.service import IdentityAccessService
from app.settings.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize or update one configured Feishu identity as a super administrator."
    )
    parser.add_argument("--scope", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--operator-source", default="deployment-command")
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()

    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        service = IdentityAccessService(create_session_factory(engine))
        result = service.bootstrap_super_admin(
            scope=args.scope,
            profile=FeishuProfile(
                subject=args.subject,
                display_name=args.display_name,
            ),
            operator_source=args.operator_source,
            request_id=args.request_id,
        )
        print(f"super administrator initialized: userId={result.user_id}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
