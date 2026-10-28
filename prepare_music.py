"""Prepare song assets; optionally verify publication history before generation."""
import argparse
import datetime as dt
import gc
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from pipeline import make_song, render, duration, validate_duration, validate_song, song_duplicate_reason, pipeline_failure_message
from music_cpu import generate
import os


def prepare(run_id, stage='all', check_history=False, vocal_gender='auto'):
    if vocal_gender not in ('auto', 'male', 'female'):
        raise ValueError('Vocal choice must be auto, male or female')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run ID')
    root = Path('output')/run_id
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root/'generation-state.json'
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    def save():
        temporary = checkpoint.with_suffix('.tmp')
        temporary.write_text(json.dumps(state))
        temporary.replace(checkpoint)
    history = []
    if check_history:
        from storage import Store
        print(json.dumps({'phase': 'verify publication history'}), flush=True)
        history = Store().load('history.json', [])
        # A rerun of an already published identity must resume, not regenerate it.
        history = [entry for entry in history if entry.get('run') != run_id]
    if check_history and (root/'song.json').exists():
        existing = validate_song(json.loads((root/'song.json').read_text()))
        if song_duplicate_reason(existing, history):
            core = {key: existing[key] for key in ('title', 'lyrics', 'prompt', 'duration', 'vocal_gender', 'song_date')
                    if key in existing}
            (root/'song-draft.json').write_text(json.dumps(core, ensure_ascii=False))
            (root/'song.json').unlink()
    if (root/'song.json').exists():
        song = validate_song(json.loads((root/'song.json').read_text()))
    else:
        song = make_song(dt.datetime.now(ZoneInfo('Asia/Dhaka')).date().isoformat(), history, root/'song-draft.json', generation_id=run_id, vocal_gender_override=vocal_gender)
        (root/'song.json').write_text(json.dumps(song, ensure_ascii=False, indent=2))
    if vocal_gender != 'auto' and song.get('vocal_gender') != vocal_gender:
        raise ValueError('Saved song voice differs from the request; use a new run ID')
    if stage == 'lyrics':
        print(json.dumps({'phase':'lyrics ready', 'run_id':run_id}), flush=True)
        return
    import lyrics_cpu
    if lyrics_cpu._model is not None:
        lyrics_cpu._model.close()
        lyrics_cpu._model = None
    gc.collect()
    if stage == 'images':
        from song_images import generate_song_images
        generate_song_images(root, song)
        print(json.dumps({'phase': 'images ready', 'run_id': run_id}), flush=True)
        return
    if stage == 'all':
        from song_images import generate_song_images
        generate_song_images(root, song)
        import image_cpu
        image_cpu._pipeline = None
        gc.collect()
    if not (root/'song.wav').exists():
        if stage == 'render':
            raise RuntimeError('Music artifact missing; publishing cannot generate through a remote service')
        generate(song, root/'song.wav', state, save)
    validate_duration(duration(root/'song.wav'))
    if stage == 'music':
        print(json.dumps({'phase':'music ready', 'run_id':run_id}), flush=True)
        return
    if not (root/'video.mp4').exists():
        render(root)
    validate_duration(duration(root/'video.mp4'))
    print(json.dumps({'run_id': run_id, 'phase': 'prepared', 'title': song['title'],
        'duration': duration(root/'video.mp4')}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--stage', choices=['all', 'lyrics', 'music', 'images', 'render'], default='all')
    parser.add_argument('--check-history', action='store_true',
                        help='Verify title and lyrics against Drive publication history before costly stages')
    parser.add_argument('--vocal-gender', choices=['auto', 'male', 'female'], default='auto')
    args = parser.parse_args()
    try:
        prepare(args.run_id, args.stage, check_history=args.check_history, vocal_gender=args.vocal_gender)
    except Exception as error:
        print(pipeline_failure_message(error), flush=True)
        raise SystemExit(1)
