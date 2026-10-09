from fastapi import FastAPI

app = FastAPI(title="한 장면 API", version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
