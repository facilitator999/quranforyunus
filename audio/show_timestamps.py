import json, sys

surah = sys.argv[1] if len(sys.argv) > 1 else '114'
reciter = sys.argv[2] if len(sys.argv) > 2 else 'minshawi'

path = f'audio/{reciter}/timestamps/{surah}.json'
d = json.load(open(path, encoding='utf-8'))
for v in d['audio_file']['timestamps']:
    words = ' '.join(f"w{s[0]}:{s[1]:.0f}-{s[2]:.0f}" for s in v['segments'])
    print(f"{v['verse_key']}: {v['timestamp_from']}-{v['timestamp_to']} | {words}")
