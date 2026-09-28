import argparse
import asyncio

from banking_api.persistence.database import session_factory
from banking_api.persistence.repositories.identities import IdentityRepository


async def _provision(*, user_id: str, issuer: str, subject: str) -> None:
    async with session_factory() as session:
        repository = IdentityRepository(session)
        existing = await repository.get_by_external_identity(issuer=issuer, subject=subject)
        if existing is not None:
            if existing.user_id != user_id:
                raise RuntimeError("External identity is already mapped to another user")
            return
        await repository.provision(user_id=user_id, issuer=issuer, subject=subject)
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly map one OIDC identity to an application user"
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    arguments = parser.parse_args()
    asyncio.run(
        _provision(
            user_id=arguments.user_id,
            issuer=arguments.issuer,
            subject=arguments.subject,
        )
    )


if __name__ == "__main__":
    main()
