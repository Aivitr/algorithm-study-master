"""[EMOJI]server.py[EMOJI]"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, '1'))
sys.path.append(os.path.join(BASE_DIR, '2'))

print("1. [EMOJI]...")
import json
import threading
from datetime import datetime
print("   [EMOJI] [EMOJI]")

print("2. [EMOJI]...")
import asyncio
import time
import wave
import cv2
import numpy as np
print("   [EMOJI] [EMOJI]")

print("3. [EMOJI]FastAPI...")
from fastapi import FastAPI, WebSocket, Form, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
print("   [EMOJI] FastAPI[EMOJI]")

print("4. [EMOJI]database[EMOJI]...")
from database import get_db, User, Meeting, Transcript, EmotionLog, AIInsight
print("   [EMOJI] database[EMOJI]")

print("5. [EMOJI]llm_service[EMOJI]...")
from llm_service import llm
print("   [EMOJI] llm_service[EMOJI]")

print("6. [EMOJI]knowledge_graph_service[EMOJI]...")
from knowledge_graph_service import kg_service
print("   [EMOJI] knowledge_graph_service[EMOJI]")

print("7. [EMOJI]ai_core[EMOJI]...")
from ai_core import engine
print("   [EMOJI] ai_core[EMOJI]")

print("8. [EMOJI]video_processor[EMOJI]...")
from video_processor import VideoEmotionAnalyzer
print("   [EMOJI] video_processor[EMOJI]")

print("\n[EMOJI]")
