from temporalio.client import Client

from app.config import settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(
            settings.temporal_address,
            namespace=settings.TEMPORAL_NAMESPACE,
        )
    return _client


async def close_temporal_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
