import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Diorama AI Server on {host}:{port}")
    uvicorn.run("diorama.app:app", host=host, port=port, reload=True)
