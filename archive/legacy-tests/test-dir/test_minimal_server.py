"""Minimal FastAPI server to test if uvicorn works"""
from fastapi import FastAPI
import uvicorn

print("Creating FastAPI app...")
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Server is working!"}

print("Starting uvicorn server...")
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
