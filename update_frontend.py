#!/usr/bin/env python3
# -*- coding: utf-8 -*-

def update_frontend():
    # [EMOJI]index.html[EMOJI]
    with open('index.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # [EMOJI]
    old_text = "d.analyzing = true; // [EMOJI]"
    new_text = "d.analyzing = false; // [EMOJI]"
    
    if old_text in content:
        # [EMOJI]
        updated_content = content.replace(old_text, new_text)
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(updated_content)
        print('[OK] [EMOJI]WebSocket[EMOJI]')
        print(f'[OK] [EMOJI] "{old_text}" [EMOJI] "{new_text}"')
    else:
        print('[ERROR] [EMOJI]')
        # [EMOJI]
        if 'analyzing' in content:
            import re
            matches = re.findall(r'd\.analyzing\s*=.*?;', content)
            if matches:
                print('[EMOJI]:', matches)

if __name__ == '__main__':
    update_frontend()