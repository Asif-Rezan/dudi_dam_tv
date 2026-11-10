"""Gentle layered storybook motion, rendered in bounded five-second clips."""
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image

VERSION = 'storybook-scene-stories-v6-fixed-duration-dissolves'
FPS = 25
SCENE_SECONDS = 5
TRANSITION = .16


def transition_clip(previous, current, target, width, height):
    """Dissolve a held outgoing frame into the incoming shot, without time loss.

    Process only two clips at once; neither lyric timing nor music is shifted.
    """
    from character_motion import verify_clip
    identity=dict(version=VERSION,previous=digest(previous),current=digest(current),
                  seconds=SCENE_SECONDS,transition=TRANSITION,width=width,height=height,fps=FPS)
    record=target.with_suffix('.json')
    if target.exists() and record.exists():
        try:
            saved=json.loads(record.read_text())
            if saved.get('identity')==identity and saved.get('sha256')==digest(target):
                verify_clip(target,width,height)
                return target
        except (OSError,ValueError):
            pass
    temp=target.with_suffix('.tmp.mp4')
    graph=(f'[0:v]trim=start={SCENE_SECONDS-1/FPS},setpts=PTS-STARTPTS,'
           f'tpad=stop_mode=clone:stop_duration={TRANSITION},fps={FPS},settb=AVTB[a];'
           f'[1:v]setpts=PTS-STARTPTS,fps={FPS},settb=AVTB[b];'
           f'[a][b]xfade=transition=fade:duration={TRANSITION}:offset=0,format=yuv420p[v]')
    try:
        run_ffmpeg(['-i',str(previous),'-i',str(current),'-filter_complex_threads','1',
                    '-filter_complex',graph,'-map','[v]','-an','-frames:v',str(FPS*SCENE_SECONDS),
                    '-c:v','libx264','-threads','4','-preset','fast','-crf','20',
                    '-movflags','+faststart',str(temp)])
        verify_clip(temp,width,height)
        temp.replace(target)
        scratch=record.with_suffix('.tmp.json')
        scratch.write_text(json.dumps(dict(identity=identity,sha256=digest(target))))
        scratch.replace(record)
    finally:
        temp.unlink(missing_ok=True)
    return target


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def render_identity(root):
    root = Path(root)
    song = json.loads((root/'song.json').read_text())
    sources = [root/'song.json',root/'song.wav',root/'thumbnail-source.png']
    sources += [root/f"scene-{s['index']:03d}-source.png" for s in song['scenes']]
    from character_motion import VERSION as character_version
    return dict(version=VERSION, character_version=character_version, fps=FPS, scene_seconds=SCENE_SECONDS,
        sources={p.name:digest(p) for p in sources})


def render_is_current(root):
    root=Path(root)
    if not (root/'video.mp4').is_file() or not (root/'render-state.json').is_file():
        return False
    try:
        return json.loads((root/'render-state.json').read_text()) == render_identity(root)
    except (OSError,ValueError,KeyError):
        return False


def run_ffmpeg(args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*args],check=True,capture_output=True)


def render_scenes(root, scenes, width=1920, height=1080, song=None):
    """Render sequentially to bound RAM; each clip covers exactly five seconds."""
    root=Path(root)
    work=root/'motion'
    work.mkdir(exist_ok=True)
    from character_motion import cached_clip, verify_clip, clip_source
    from scene_actions import motion_prompt
    clips=[]
    for scene in scenes:
        index=scene['index']
        source=clip_source(root,song or {},index)
        target=work/f'clip-{index:03d}.mp4'
        with Image.open(source) as image:
            image.verify()
        if not cached_clip(source,target,width,height,index,motion_prompt(scene)):
            raise RuntimeError(f'Scene {index} needs current character-motion clips; regenerate its image shard')
        verify_clip(target,width,height)
        clips.append(target)
    stitched=[clips[0]] if clips else []
    for previous,current in zip(clips,clips[1:]):
        stitched.append(transition_clip(previous,current,work/('transition-'+current.name),width,height))
    listing=work/'clips.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in stitched))
    return listing


def render_animated(root, song):
    from pipeline import duration,validate_duration
    root=Path(root)
    identity=render_identity(root)
    listing=render_scenes(root,song['scenes'],song=song)
    from thumbnail_export import export_thumbnail
    export_thumbnail(root/'thumbnail-source.png',root/'thumbnail.jpg')
    temp=root/'video.tmp.mp4'
    run_ffmpeg(['-f','concat','-safe','1','-i',str(listing),'-i',str(root/'song.wav'),
        '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
        '-t',str(song['duration']),'-movflags','+faststart',str(temp)])
    measured=duration(temp)
    validate_duration(measured)
    if abs(measured-song['duration'])>.1:
        raise ValueError('Animated video differs from storyboard duration')
    temp.replace(root/'video.mp4')
    checkpoint=root/'render-state.tmp'
    checkpoint.write_text(json.dumps(identity,indent=2))
    checkpoint.replace(root/'render-state.json')
