"""Development/production entry point: ``python main.py`` (or ``python -m diorama.server``)."""

import uvicorn

from diorama.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    print(f"Starting Diorama AI Server on {settings.host}:{settings.port}")
    uvicorn.run("diorama.app:app", host=settings.host, port=settings.port, reload=settings.reload)
