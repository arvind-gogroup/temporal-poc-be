"""Singleton Temporal client shared across the API process.

The client is initialised once during FastAPI lifespan startup
(``app/main.py``) and stored on ``app.state.temporal_client``.
These helpers manage the module-level singleton used by the worker process,
which does not have access to FastAPI app state.
"""

from temporalio.client import Client

from app.config import settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Return the shared Temporal client, creating it on first call.

    Uses a module-level singleton so the gRPC connection is not re-established
    on every request. Safe to call concurrently — the first awaited call
    initialises the client; subsequent calls return the cached instance.

    Returns:
        A connected ``temporalio.client.Client`` instance.
    """
    global _client
    if _client is None:
        _client = await Client.connect(
            settings.temporal_address,
            namespace=settings.TEMPORAL_NAMESPACE,
        )
    return _client


async def close_temporal_client() -> None:
    """Close the shared Temporal client and reset the singleton.

    Called during FastAPI lifespan shutdown. Safe to call even if the client
    was never initialised.
    """
    global _client
    if _client is not None:
        await _client.close()
        _client = None
