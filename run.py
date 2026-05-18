import uvicorn
import os

if __name__ == "__main__":
    import startup  # seed DB if empty
    port = int(os.environ.get("PORT", 8001))
    host = "0.0.0.0" if os.environ.get("PORT") else "localhost"
    uvicorn.run("app.main:app", host=host, port=port, reload=(host == "localhost"))
