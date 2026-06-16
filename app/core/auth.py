"""
app/core/auth.py
────────────────
API Key authentication dependency for Fin-Guardian AI.

Usage:
    @app.post("/endpoint", dependencies=[Depends(require_api_key)])
    async def my_endpoint(tx: IncomingTransaction):
        ...

Setting API keys:
    In .env:  FG_API_KEYS=key-1,key-2,key-3
    In prod:  Set FG_API_KEYS environment variable on deployment platform.
"""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.settings import settings

# The header name clients must send: X-API-Key: <your-key>
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """
    FastAPI dependency: validates that the X-API-Key header is present
    and matches one of the configured keys.

    Returns the validated key string on success.
    Raises HTTP 403 on failure.

    Usage:
        from app.core.auth import require_api_key
        @app.post("/endpoint", dependencies=[Depends(require_api_key)])
    """
    valid_keys = settings.api_keys_list

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing API key. Include X-API-Key header.",
        )

    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key
