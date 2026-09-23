#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[EMOJI]"""

from database import SessionLocal, LearningReport, User, Exercise
import json

db = SessionLocal()

print('=== [EMOJI] ===')
reports = db.query(LearningReport).all()
for r in reports:
    user = db.query(User).filter(User.id == r.user_id).first()
    exercises = db.query(Exercise).filter(Exercise.report_id == r.id).all()
    
    print(f'[EMOJI]ID: {r.id}')
    print(f'[EMOJI]ID: {r.user_id} ({user.username if user else "[EMOJI]"})')
    print(f'[EMOJI]ID: {r.meeting_id}')
    print(f'[EMOJI]: {json.dumps(r.report_data, ensure_ascii=False)}')
    print(f'[EMOJI]: {len(exercises)}')
    print(f'[EMOJI]: {r.created_at}')
    print('---')

print(f'\n[EMOJI] {len(reports)} [EMOJI]')

# [EMOJI]
users = db.query(User).all()
for user in users:
    user_reports = db.query(LearningReport).filter(LearningReport.user_id == user.id).all()
    print(f'{user.username} ({user.role}): {len(user_reports)} [EMOJI]')

db.close()
