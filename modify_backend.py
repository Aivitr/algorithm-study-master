#!/usr/bin/env python3
# -*- coding: utf-8 -*-

def modify_backend():
    with open('server.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # [EMOJI]
    old_segment = '''                print(f"[NOTE] [EMOJI]: {text} ([EMOJI]...)")

                # === [FAST] [EMOJI]:[EMOJI]([EMOJI] AI)===
                yield {
                    "type": "new_speech_fast",  # [EMOJI]
                    "username": username,
                    "text": text,
                    "tags": {"emotion": vis_emotion, "action": body_action},
                    "timestamp": timestamp,  # [EMOJI]:[EMOJI]
                    "goals": meeting.knowledge_points  # [EMOJI]
                }

                # === [EMOJI]===
                # [EMOJI]
                emo_str = f"{vis_emotion}|{body_action}"
                if len(emo_str) > 90: emo_str = emo_str[:90]

                db.add(EmotionLog(
                    meeting_id=meeting_id, user_id=user.id,
                    emotion_type=emo_str, intensity=0.8,
                    timestamp=datetime.now()  # [EMOJI]
                ))
                db.commit()

                # === [EMOJI] [EMOJI]:[EMOJI] AI ===
                trans = Transcript(
                    meeting_id=meeting_id, user_id=user.id, content=text,
                    audio_file_path=f"storage/audio_chunks/{a_name}",
                    emotion_tag=vis_emotion, body_action=body_action,
                    timestamp=datetime.now()
                )
                db.add(trans);
                db.commit()  # [EMOJI],[EMOJI] ID

                relevance = 0;
                hint = None;
                updated_goals = None
                quality_score = 50  # [EMOJI]
                quality_feedback = ""

                # [EMOJI] AI,[EMOJI]
                if len(text) > 2:
                    try:
                        recents = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).order_by(
                            Transcript.id.desc()).limit(3).all()
                        ctx = "\\n".join([f"{t.user.username}:{t.content}" for t in recents]

                        # === [STAR] [EMOJI]: [EMOJI] ===
                        score_result = llm.score_speech_quality(text, meeting.topic, ctx)
                        quality_score = score_result.get("score", 50)
                        quality_feedback = score_result.get("feedback", "")

                        # [EMOJI] (3[EMOJI]+)
                        analysis = llm.analyze_progress(meeting.topic, meeting.knowledge_points, ctx, username)

                        if analysis:
                            relevance = analysis.get("relevance", 0)
                            hint = analysis.get("hint", "")
                            updated_goals = analysis.get("updated_goals")
                    except Exception as e:
                        print(f"AI Error: {e}")
                        # [EMOJI]AI[EMOJI]
                        relevance = 0
                        hint = ""
                        quality_score = 50
                        quality_feedback = "AI[EMOJI]"

                # [EMOJI]
                if updated_goals: meeting.knowledge_points = updated_goals
                trans.relevance_score = relevance
                trans.quality_score = quality_score
                trans.quality_feedback = quality_feedback
                db.commit()
                if hint:
                    db.add(AIInsight(meeting_id=meeting_id, target_user=username, content=hint, type="hint"))
                    db.commit()'''

    # [EMOJI]
    new_segment = '''                print(f"[NOTE] [EMOJI]: {text} ([EMOJI]...)")

                # === [STAR] [EMOJI]AI[EMOJI] ===
                relevance = 0;
                hint = None;
                updated_goals = None
                quality_score = 50  # [EMOJI]
                quality_feedback = ""

                # [EMOJI] AI,[EMOJI]
                if len(text) > 2:
                    try:
                        recents = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).order_by(
                            Transcript.id.desc()).limit(3).all()
                        ctx = "\\n".join([f"{t.user.username}:{t.content}" for t in recents]

                        # === [STAR] [EMOJI]: [EMOJI] ===
                        score_result = llm.score_speech_quality(text, meeting.topic, ctx)
                        quality_score = score_result.get("score", 50)
                        quality_feedback = score_result.get("feedback", "")

                        # [EMOJI] (3[EMOJI]+)
                        analysis = llm.analyze_progress(meeting.topic, meeting.knowledge_points, ctx, username)

                        if analysis:
                            relevance = analysis.get("relevance", 0)
                            hint = analysis.get("hint", "")
                            updated_goals = analysis.get("updated_goals")
                    except Exception as e:
                        print(f"AI Error: {e}")
                        # [EMOJI]AI[EMOJI]
                        relevance = 0
                        hint = ""
                        quality_score = 50
                        quality_feedback = "AI[EMOJI]"

                # === [EMOJI]===
                # [EMOJI]
                emo_str = f"{vis_emotion}|{body_action}"
                if len(emo_str) > 90: emo_str = emo_str[:90]

                db.add(EmotionLog(
                    meeting_id=meeting_id, user_id=user.id,
                    emotion_type=emo_str, intensity=0.8,
                    timestamp=datetime.now()  # [EMOJI]
                ))
                db.commit()

                # === [FAST] [EMOJI]:[EMOJI]([EMOJI]AI[EMOJI])===
                yield {
                    "type": "new_speech_fast",  # [EMOJI]
                    "username": username,
                    "text": text,
                    "tags": {"emotion": vis_emotion, "action": body_action},
                    "timestamp": timestamp,  # [EMOJI]:[EMOJI]
                    "goals": meeting.knowledge_points,  # [EMOJI]
                    "quality_score": quality_score,  # [EMOJI]AI[EMOJI]
                    "quality_feedback": quality_feedback  # [EMOJI]AI[EMOJI]
                }

                # === [EMOJI] [EMOJI]:[EMOJI] ===
                trans = Transcript(
                    meeting_id=meeting_id, user_id=user.id, content=text,
                    audio_file_path=f"storage/audio_chunks/{a_name}",
                    emotion_tag=vis_emotion, body_action=body_action,
                    timestamp=datetime.now()
                )
                db.add(trans);
                db.commit()  # [EMOJI],[EMOJI] ID

                # [EMOJI]
                if updated_goals: meeting.knowledge_points = updated_goals
                trans.relevance_score = relevance
                trans.quality_score = quality_score
                trans.quality_feedback = quality_feedback
                db.commit()
                if hint:
                    db.add(AIInsight(meeting_id=meeting_id, target_user=username, content=hint, type="hint"))
                    db.commit()'''

    # [EMOJI]
    if old_segment in content:
        # [EMOJI]
        new_content = content.replace(old_segment, new_segment)
        with open('server.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print('[OK] [EMOJI]AI[EMOJI]')
    else:
        print('[ERROR] [EMOJI]')
        # [EMOJI]
        if '"text": text,' in content and '"goals": meeting.knowledge_points' in content:
            print('[BULB] [EMOJI]')

if __name__ == '__main__':
    modify_backend()