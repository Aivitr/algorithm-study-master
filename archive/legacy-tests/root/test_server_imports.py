"""Find which import is blocking server.py startup"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, '1'))
sys.path.append(os.path.join(BASE_DIR, '2'))

print("Step 1: Basic imports")
import json
import threading
from datetime import datetime

print("Step 2: FastAPI imports")
from fastapi import FastAPI
from sqlalchemy.orm import Session

print("Step 3: Importing database module")
from database import get_db, User, Meeting

print("Step 4: Importing llm_service")
from llm_service import llm

print("Step 5: Importing knowledge_graph_service")
from knowledge_graph_service import kg_service

print("Step 6: Importing ai_core")
from ai_core import engine

print("Step 7: Importing video_processor")
from video_processor import VideoEmotionAnalyzer

print("All imports successful!")
