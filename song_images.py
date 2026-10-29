"""Generate a distinct lyric scene for each five-second slot, with resumable cache."""
import hashlib
import json
import os
from pathlib import Path
from PIL import Image
from image_cpu import MODEL, REVISION


def image_plan(song):
    from kids_rhymes import validate_storyboard
    validate_storyboard(song)
    identity = hashlib.sha256(json.dumps(song, sort_keys=True).encode()).hexdigest()
    entries = [(f"scene-{s['index']:03d}", s['prompt']) for s in song['scenes']]
    entries.append(('thumbnail', song['scenes'][0]['prompt'] + ' Close-up joyful faces, colorful nursery rhyme thumbnail.'))
    return [dict(kind=kind, prompt=prompt, seed=int(hashlib.sha256((identity+kind).encode()).hexdigest()[:8],16),
        model=MODEL, revision=REVISION, width=int(os.getenv('CPU_IMAGE_WIDTH','1024')),
        height=int(os.getenv('CPU_IMAGE_HEIGHT','576')), steps=int(os.getenv('CPU_IMAGE_STEPS','16')),
        visual_style='dudi-storybook-v2', allow_text=False) for kind,prompt in entries]


def generate_song_images(root, song):
    from image_cpu import generate
    root = Path(root)
    shard, count = int(os.getenv('IMAGE_SHARD','0')), int(os.getenv('IMAGE_SHARDS','1'))
    if not 0 <= shard < count:
        raise ValueError('Invalid image shard')
    manifest = root/f'image-manifest-{shard:02d}.json'
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    completed = {}
    for i, plan in enumerate(image_plan(song)):
        if i % count != shard:
            continue
        kind = plan['kind']
        target = root/f'{kind}-source.png'
        valid = False
        if previous.get(kind) == plan and target.exists():
            try:
                with Image.open(target) as im:
                    im.verify()
                valid = True
            except (OSError,ValueError):
                pass
        if not valid:
            temporary = target.with_suffix('.tmp.png')
            generate(plan['prompt'], temporary, seed=plan['seed'], allow_text=False)
            with Image.open(temporary) as im:
                im.verify()
            temporary.replace(target)
        completed[kind] = plan
        temp = manifest.with_suffix('.tmp')
        temp.write_text(json.dumps(completed,indent=2))
        temp.replace(manifest)
    return completed
