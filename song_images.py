"""Generate two distinct, reproducible SSD-1B scenes for every original song."""
import hashlib
import json
import os
import re
from pathlib import Path
from PIL import Image
from image_cpu import MODEL, REVISION, GUIDANCE_SCALE, negative_prompt
from artwork import visual_mood


# Changing this contract invalidates old poster/lettering cache entries.
VISUAL_STYLE = 'heart-mind-textfree-cinematic-v2'


def scene_detail(value, fallback, mood):
    """Retain a song's action/place without old poster, typography or layout commands."""
    if not isinstance(value, str) or not value.strip():
        value = fallback
    clauses = re.split(r'[.!?;]+', value)
    clauses = [clause for clause in clauses if not re.search(
        r'\b(?:title|lettering|typography|watermark|logo|badge|poster|text|brushwork)\b', clause, re.I)]
    scene = ' '.join(clauses).strip() or fallback
    actor = 'young adult woman' if mood == 'healing' else 'young adult couple'
    scene = re.sub(r'\b(?:elderly|old|older|grey-haired|gray-haired|middle-aged)\s+(?:man|gentleman|male)\b', actor, scene, flags=re.I)
    scene = re.sub(r'\b(?:at|on) (?:the )?(?:far )?(?:left|right)(?: half| side)?\b', '', scene, flags=re.I)
    scene = ' '.join(scene.split()[:16]).rstrip(',.;')
    return scene


def image_plan(song):
    identity = hashlib.sha256((song['title'] + '\n' + song['lyrics']).encode()).hexdigest()
    mood = visual_mood(song)
    # Couples retain the relationship story even for separation; healing may use
    # one expressive female lead rather than an unrelated male stock portrait.
    subjects = {
        'romance': 'Beautiful adult South Asian couple aged 25-35, tender eye contact',
        'heartbreak': 'Beautiful adult South Asian couple aged 25-35, quiet longing, turned apart',
        'healing': 'Beautiful adult South Asian woman aged 25-35, hopeful expressive eyes',
    }
    defaults = {
        'romance': 'sharing a quiet reunion beside a lantern in a moonlit bookshop',
        'heartbreak': 'parting on a rainy railway platform with warm station lights reflected on wet ground',
        'healing': 'walking through a green meadow toward soft sunrise with a calm hopeful smile',
    }
    plans = []
    for kind, field in (('background', 'background_prompt'), ('thumbnail', 'thumbnail_prompt')):
        scene = scene_detail(song.get(field), defaults[mood], mood)
        if kind == 'thumbnail':
            framing = ('Close chest-up two-shot, both faces distinct and fully visible' if mood != 'healing'
                       else 'Close chest-up portrait, face fully visible, natural pose')
            finish = 'Soft face light, natural skin, teal-gold bokeh, fully clothed, no text.'
        else:
            framing = 'Wide environmental scene, people right-center, scenic depth, clear lower edge'
            finish = 'Soft face light, natural skin, rich scenery, fully clothed, no text.'
        # Subject, emotion and real lyric setting lead the limited text encoders.
        prompt = 'Cinematic photograph. ' + subjects[mood] + '. ' + framing + '. ' + scene + '. ' + finish
        seed = int(hashlib.sha256((identity + kind).encode()).hexdigest()[:8], 16)
        plans.append(dict(kind=kind, prompt=prompt, seed=seed,
                          model=MODEL, revision=REVISION, visual_style=VISUAL_STYLE,
                          width=int(os.getenv('CPU_IMAGE_WIDTH', '1024')),
                          height=int(os.getenv('CPU_IMAGE_HEIGHT', '576')),
                          steps=int(os.getenv('CPU_IMAGE_STEPS', '16')),
                          guidance_scale=GUIDANCE_SCALE,
                          negative_prompt=negative_prompt(), allow_text=False))
    return plans


def generate_song_images(root, song):
    from image_cpu import generate
    root = Path(root)
    manifest_path = root/'image-manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    completed = {}
    for plan in image_plan(song):
        kind = plan['kind']
        target = root/f'{kind}-source.png'
        valid = False
        if previous.get(kind) == plan and target.exists():
            try:
                with Image.open(target) as image:
                    image.verify()
                valid = True
            except (OSError, ValueError):
                pass
        if not valid:
            temporary = target.with_suffix('.tmp.png')
            generate(plan['prompt'], temporary, seed=plan['seed'], allow_text=plan['allow_text'])
            with Image.open(temporary) as image:
                image.verify()
            temporary.replace(target)
        completed[kind] = plan
        # Save after each scene so retries preserve completed expensive CPU work.
        temp_manifest = manifest_path.with_suffix('.tmp')
        temp_manifest.write_text(json.dumps(completed, indent=2))
        temp_manifest.replace(manifest_path)
    return completed
