"""Offline rhyme planning, checkpointed music parts and five-second story scenes."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

REFRAIN = 'dudi dudi dam dam dudi dudi dam'
from rhyme_writer import write_rhyme

def make_song(day, history, draft_path=None, generation_id=None, vocal_gender_override='female'):
    if vocal_gender_override not in ('auto', 'female'):
        raise ValueError('Dudi Dam TV uses female vocals')
    seconds = int(os.getenv('VIDEO_DURATION_SECONDS', '600'))
    if not 480 <= seconds <= 720 or seconds % 5:
        raise ValueError('VIDEO_DURATION_SECONDS must be 480-720, in five-second steps')
    identity = generation_id or day
    written = write_rhyme(day, identity, seconds, history, draft_path)
    outline = written['outline']
    scenes = []
    for section in written['sections']:
        for row in section:
            # Keep the lyric action before the image encoder token limit.
            prompt=(row['visual'] + '. Cute colorful 3D storybook cartoon. '
                + outline.get('characters', '') + '. ' + outline.get('visual_world', '')
                + '. Rounded soft shapes, adorable expressive faces, bright pastel colors, gentle playful mood, wide landscape, no text.')
            for lyric in (row['lyric'], REFRAIN):
                i=len(scenes)
                scenes.append(dict(index=i,start=i*5,end=(i+1)*5,lyric=lyric,prompt=prompt))
    scenes=scenes[:seconds//5]
    outline=written['outline']
    song = dict(title=outline['title'], lyrics='\n'.join(scene['lyric'] for scene in scenes),duration=seconds,
        prompt='Joyful nursery rhyme, cute sweet adult female singing voice, clear English diction, playful dudi dudi dam dam refrain, major key, 100 BPM, ukulele, xylophone, soft handclaps, gentle bass, warm child-friendly mix, no shouting.',
        description=outline['description'],story_summary=outline['story_summary'],
        visual_identity=dict(characters=outline.get('characters',''), world=outline.get('visual_world','')),
        lyric_writer=dict(backend='local-qwen-cpu',version=written['writer_version'],novelty_checked=True),
        vocal_gender='female',song_date=day,scenes=scenes,
        tags=['Dudi Dam TV','kids rhymes','nursery rhymes','Dudi Dudi Dam Dam','kids dance'])
    validate_storyboard(song)
    return song


def validate_storyboard(song):
    if song.get('vocal_gender') != 'female':
        raise ValueError('Female vocal required')
    scenes = song.get('scenes', [])
    if len(scenes) != song['duration'] / 5:
        raise ValueError('One scene per five seconds required')
    for i, scene in enumerate(scenes):
        if (scene.get('index'), scene.get('start'), scene.get('end')) != (i, i*5, (i+1)*5):
            raise ValueError('Non-contiguous storyboard')
        if not scene.get('lyric') or not scene.get('prompt'):
            raise ValueError('Scene lyric and prompt required')
    if song['lyrics'] != '\n'.join(scene['lyric'] for scene in scenes):
        raise ValueError('Storyboard lyrics must match sung lyrics')


def upload_description(song):
    return song['description'] + '\n\nOriginal kids rhyme arrangement by Dudi Dam TV.\n#KidsRhymes #DudiDamTV #NurseryRhymes'


def metadata_tags(song):
    return list(dict.fromkeys(song.get('tags', []) + ['Dudi Dam TV', 'kids rhymes']))


def generate_music(song, target, state, save):
    from pipeline import validate_song, validate_duration, duration
    from music_cpu import generate_segment
    validate_song(song)
    if target.exists():
        validate_duration(duration(target))
        return
    # ACE-Step documents up to 600 seconds per request. Short independent parts
    # keep 8-12 minute episodes within that contract, with no audio looping.
    parts = []
    scenes = song['scenes']
    for i in range(0, len(scenes), 24):
        group = scenes[i:i+24]
        part = dict(song, duration=len(group)*5, lyrics='\n'.join(s['lyric'] for s in group), _segment=True)
        path = target.parent / f'part-{i//24:03d}.wav'
        part_state = state.setdefault('parts', {}).setdefault(str(i//24), {})
        generate_segment(part, path, part_state, save)
        parts.append(path)
    # Normalize every part to the planned boundary, refusing short generations.
    normalized = []
    for i, path in enumerate(parts):
        requested = min(120, song['duration']-i*120)
        if duration(path) < requested - .25:
            raise RuntimeError('Music part is too short; regenerate rather than pad or loop')
        dest = target.parent / f'normalized-{i:03d}.wav'
        subprocess.run(['ffmpeg', '-y', '-i', str(path), '-t', str(requested), '-ar', '44100', '-ac', '2', str(dest)], check=True, capture_output=True)
        normalized.append(dest)
    listing = target.parent/'audio-parts.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in normalized))
    temporary = target.with_suffix('.tmp.wav')
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '1', '-i', str(listing), '-c', 'copy', str(temporary)], check=True, capture_output=True)
    validate_duration(duration(temporary))
    temporary.replace(target)
    state['audio_ready'] = True
    save()


def render_video(root):
    from PIL import Image, ImageOps
    from pipeline import duration, validate_duration, validate_song
    root = Path(root)
    song = validate_song(json.loads((root/'song.json').read_text()))
    seconds = duration(root/'song.wav')
    validate_duration(seconds)
    if abs(seconds-song['duration']) > .25:
        raise ValueError('Audio does not match storyboard duration')
    from motion_video import render_animated
    render_animated(root, song)
