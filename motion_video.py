"""Gentle layered storybook motion, rendered in bounded five-second clips."""
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw

VERSION = 'storybook-motion-v2-visible-bubbles'
FPS = 25
SCENE_SECONDS = 5
TRANSITION = .28


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
    return dict(version=VERSION, fps=FPS, scene_seconds=SCENE_SECONDS,
        sources={p.name:digest(p) for p in sources})


def render_is_current(root):
    root=Path(root)
    if not (root/'video.mp4').is_file() or not (root/'render-state.json').is_file():
        return False
    try:
        return json.loads((root/'render-state.json').read_text()) == render_identity(root)
    except (OSError,ValueError,KeyError):
        return False


def bubble_sprite(target):
    """A small original decorative overlay; transparent center keeps faces visible."""
    im=Image.new('RGBA',(160,160))
    draw=ImageDraw.Draw(im)
    draw.ellipse((14,14,146,146),fill=(166,225,255,48),outline=(99,154,231,230),width=6)
    draw.ellipse((20,20,140,140),outline=(244,253,255,240),width=3)
    draw.arc((19,19,141,141),25,145,fill=(248,151,218,245),width=6)
    draw.arc((27,27,133,133),190,270,fill=(255,255,255,255),width=7)
    draw.ellipse((39,37,54,52),fill=(255,255,255,245))
    draw.ellipse((104,107,113,116),fill=(255,244,255,220))
    im.save(target)


def scene_filter(index, width, height, previous=False):
    # Motion is modest, never exposing image edges. Alternate travel direction,
    # with a small 100-BPM pulse matching the arrangement's requested tempo.
    # This is a tempo guide, not an audio beat detector or character rig.
    phase=(index%4)*1.570796327
    travel=1 if index%2==0 else -1
    zoom=f'1.075+0.025*on/{FPS*SCENE_SECONDS-1}+0.003*(1-cos(2*PI*on/{FPS}/0.6))'
    x=f'(iw-iw/zoom)*(0.5+{travel}*0.27*sin(PI*(on/{FPS*SCENE_SECONDS-1}-0.5)))'
    y=f'(ih-ih/zoom)*(0.5+0.10*sin(2*PI*on/{FPS}/3+{phase}))'
    filters=[f"[0:v]scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={FPS*SCENE_SECONDS}:s={width}x{height}:fps={FPS},setsar=1,format=rgba[scene]"]
    base='scene'
    if previous:
        filters += [f'[scene]fade=t=in:st=0:d={TRANSITION}:alpha=1[incoming]',
            f'[2:v]scale={width}:{height},setsar=1,format=rgba[previous]',
            '[previous][incoming]overlay=shortest=1[transition]']
        base='transition'
    filters += ['[1:v]split=4[b1][b2][b3][b4]']
    # Keep decoration near the frame edges, with separate drift for parallax.
    for j,(size,xpos,speed) in enumerate(((.14,.025,10),(.115,.85,12),(.085,.16,9),(.075,.77,11)),1):
        px=max(12,round(width*size)//2*2)
        filters.append(f'[b{j}]scale={px}:{px},format=rgba[s{j}]')
        bx=f'W*{xpos}+W*0.018*sin(2*PI*t/4+{phase+j})'
        by=f'H*(1.12-mod(t/{speed}+{j*.23},1.3))'
        filters.append(f"[{base}][s{j}]overlay=x='{bx}':y='{by}':shortest=1[layer{j}]")
        base=f'layer{j}'
    filters.append(f'[{base}]format=yuv420p[out]')
    return ';'.join(filters)


def run_ffmpeg(args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*args],check=True,capture_output=True)


def render_scenes(root, scenes, width=1920, height=1080):
    """Render sequentially to bound RAM; each clip covers exactly five seconds."""
    root=Path(root)
    work=root/'motion'
    work.mkdir(exist_ok=True)
    sprite=work/'bubble.png'
    bubble_sprite(sprite)
    previous=None
    clips=[]
    for scene in scenes:
        index=scene['index']
        source=root/f'scene-{index:03d}-source.png'
        # Fail before FFmpeg starts when a required illustration is absent/corrupt.
        with Image.open(source) as im:
            im.verify()
        target=work/f'clip-{index:03d}.mp4'
        args=['-i',str(source),'-loop','1','-framerate',str(FPS),'-i',str(sprite)]
        if previous:
            args += ['-loop','1','-framerate',str(FPS),'-i',str(previous)]
        args += ['-filter_complex_threads','1','-filter_complex',scene_filter(index,width,height,previous is not None),
            '-map','[out]','-an','-frames:v',str(FPS*SCENE_SECONDS),'-r',str(FPS),
            '-c:v','libx264','-threads','4','-preset','fast','-crf','20','-pix_fmt','yuv420p',str(target)]
        print(json.dumps({'phase':'animate scene','scene':index+1,'total':len(scenes)}),flush=True)
        run_ffmpeg(args)
        previous=work/'previous-frame.png'
        run_ffmpeg(['-sseof','-0.2','-i',str(target),'-vf','reverse','-frames:v','1','-update','1',str(previous)])
        clips.append(target)
    listing=work/'clips.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in clips))
    return listing


def render_animated(root, song):
    from pipeline import duration,validate_duration
    root=Path(root)
    identity=render_identity(root)
    listing=render_scenes(root,song['scenes'])
    with Image.open(root/'thumbnail-source.png') as im:
        from PIL import ImageOps
        ImageOps.fit(im.convert('RGB'),(1280,720)).save(root/'thumbnail.jpg',quality=92)
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
