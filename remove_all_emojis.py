"""Remove all emoji characters from Python files to fix GBK encoding errors"""
import os
import re

# Emoji to text replacements
EMOJI_MAP = {
    '[LOGIN]': '[LOGIN]', '[DB]': '[DB]', '[OK]': '[OK]', '[ERROR]': '[ERROR]', '[WARN]': '[WARN]',
    '[VOL++]': '[AUDIO]', '[ZOOM]': '[SEARCH]', '[STATS]': '[STATS]', '[UP]': '[UP]', '[DOWN]': '[DOWN]',
    '[MIC]': '[MIC]', '[BULB]': '[IDEA]', '[AI]': '[AI]', '[NOTE]': '[NOTE]', '[PROCESS]': '[PROCESS]',
    '[SEND]': '[SEND]', '[DATA]': '[DATA]', '[FAST]': '[FAST]', '[TARGET]': '[TARGET]', '[CLEAN]': '[CLEAN]',
    '[Q]': '[Q]', '[MSG]': '[MSG]', '[FILE]': '[FILE]', '[DONE]': '[DONE]', '[SAVE]': '[SAVE]',
    '[RUN]': '[RUN]', '[USERS]': '[USERS]', '[WEB]': '[WEB]', '[TIME]': '[TIME]', '[STYLE]': '[STYLE]',
    '[CONFIG]': '[CONFIG]', '[LIST]': '[LIST]', '[START]': '[START]', '[STOP]': '[STOP]', '[CODE]': '[CODE]',
    '[KEY]': '[KEY]', '[PIN]': '[PIN]', '[LEARN]': '[LEARN]', '[BOOK]': '[BOOK]', '[BELL]': '[NOTIFY]',
    '[FAST]': '[FAST]', '[STAR]': '[STAR]', '[EVENT]': '[EVENT]', '[WIN]': '[WIN]', '[PHOTO]': '[PHOTO]',
    '[VIDEO]': '[VIDEO]', '[REC]': '[REC]', '[PAUSE]': '[PAUSE]', '[PLAY]': '[PLAY]', '[STOP]': '[STOP]',
    '[MUTE]': '[MUTE]', '[VOL]': '[VOL]', '[VOL+]': '[VOL+]', '[VOL++]': '[VOL++]', '[ANNOUNCE]': '[ANNOUNCE]',
    '[LOUD]': '[LOUD]', '[HORN]': '[HORN]', '[BELL]': '[BELL]', '[SILENT]': '[SILENT]', '[MUSIC]': '[MUSIC]',
    '[NOTES]': '[NOTES]', '[SCORE]': '[SCORE]', '[PIANO]': '[PIANO]', '[DRUM]': '[DRUM]', '[GUITAR]': '[GUITAR]',
    '[TRUMPET]': '[TRUMPET]', '[SAX]': '[SAX]', '[VIOLIN]': '[VIOLIN]', '[BANJO]': '[BANJO]', '[DRUM2]': '[DRUM2]',
    '[ACCORDION]': '[ACCORDION]', '[MIC2]': '[MIC2]', '[SLIDER]': '[SLIDER]', '[KNOBS]': '[KNOBS]', '[RADIO]': '[RADIO]',
    '[TV]': '[TV]', '[CAMERA]': '[CAMERA]', '[PHOTO2]': '[PHOTO2]', '[VHS]': '[VHS]', '[ZOOM]': '[ZOOM]',
    '[ZOOM2]': '[ZOOM2]', '[CANDLE]': '[CANDLE]', '[BULB]': '[BULB]', '[FLASH]': '[FLASH]', '[LANTERN]': '[LANTERN]',
}

def remove_emojis_from_file(filepath):
    """Remove all emoji characters from a Python file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # Replace all emojis with text equivalents
        for emoji, replacement in EMOJI_MAP.items():
            content = content.replace(emoji, replacement)

        # Remove any remaining emojis using regex (catches ones not in our map)
        # This regex matches most emoji characters
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"  # supplemental symbols
            "\U0001FA00-\U0001FA6F"  # extended symbols
            "]+",
            flags=re.UNICODE
        )
        content = emoji_pattern.sub('[EMOJI]', content)

        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def main():
    """Process all Python files in the directory"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    modified_count = 0

    print("Removing emoji characters from Python files...")

    for root, dirs, files in os.walk(root_dir):
        # Skip virtual environments and cache directories
        dirs[:] = [d for d in dirs if d not in ['.venv', 'venv', '__pycache__', '.git']]

        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                if remove_emojis_from_file(filepath):
                    print(f"  Modified: {os.path.relpath(filepath, root_dir)}")
                    modified_count += 1

    print(f"\nDone! Modified {modified_count} files.")

if __name__ == "__main__":
    main()
