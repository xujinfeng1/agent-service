import uvicorn
from src.config import config

if __name__ == "__main__":
    uvicorn.run(
        "src.api:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info",
    )
