from contextlib import AbstractAsyncContextManager
from types import TracebackType

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def normalize_checkpoint_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class LangGraphCheckpointManager:
    def __init__(self, database_url: str, *, strict_msgpack: bool = True) -> None:
        self.database_url = normalize_checkpoint_database_url(database_url)
        self.strict_msgpack = strict_msgpack
        self.saver: AsyncPostgresSaver | None = None
        self._context: AbstractAsyncContextManager[AsyncPostgresSaver] | None = None

    async def start(self) -> AsyncPostgresSaver:
        serializer = JsonPlusSerializer(
            allowed_msgpack_modules=None if self.strict_msgpack else True
        )
        self._context = AsyncPostgresSaver.from_conn_string(
            self.database_url,
            serde=serializer,
        )
        self.saver = await self._context.__aenter__()
        await self.saver.setup()
        return self.saver

    async def close(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None
        self.saver = None

    async def __aenter__(self) -> AsyncPostgresSaver:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context is not None:
            await self._context.__aexit__(exc_type, exc, traceback)
        self._context = None
        self.saver = None
