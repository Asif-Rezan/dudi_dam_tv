"""Hindi song -> ACE-Step 1.5 -> HD visualizer -> verified public YouTube video."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from zoneinfo import ZoneInfo
from storage import Store, required


class DuplicateSongError(RuntimeError):
    """A safe diagnostic; never expose raw API responses or checkpoint contents."""


def pipeline_failure_message(error):
    if isinstance(error, DuplicateSongError):
        return ('Pipeline failed [duplicate_song]: lyrics or title already published. '
                'Create a fresh song with a new run ID; do not retry duplicate media.')
    return ('Pipeline failed: ' + type(error).__name__ +
            '. Inspect checkpoint and configuration.')


def song_duplicate_reason(song, history, run_id=None):
    digest = hashlib.sha256(normalize_lyrics(song['lyrics']).encode()).hexdigest()
    entries = [entry for entry in history if run_id is None or entry.get('run') != run_id]
    if any(entry.get('hash') == digest for entry in entries):
        return 'lyrics'
    if any(entry.get('title') == song['title'] for entry in entries):
        return 'title'
    return None


def lyric_title_candidates(lyrics, search_term, year):
    """Bounded public titles from actual sung lines, without model retries."""
    candidates = []
    suffix = f' | {search_term} {year}'
    for line in normalize_lyrics(lyrics).splitlines():
        line = re.sub(r'\[[^]]*\]', '', line).strip()
        words = re.findall(r'[\u0900-\u097f]+', line)
        phrase = ' '.join(words[:6])
        if len(words) < 2 or not phrase:
            continue
        while len(phrase + suffix) > 100 and ' ' in phrase:
            phrase = phrase.rsplit(' ', 1)[0]
        title = phrase + suffix
        if len(title) <= 100 and title not in candidates:
            candidates.append(title)
    return candidates


def normalize_lyrics(text):
    """Repair escaped layout markers without changing the Hindi words."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\\+(?:r\\+n|n|r)', '\n', text)
    return re.sub(r'\\+t', ' ', text)


def validate_song(song):
    for field in ('title', 'lyrics', 'prompt', 'description'):
        if not isinstance(song.get(field), str) or not song[field].strip():
            raise ValueError('Missing song ' + field)
    if len(song['title']) > 100 or len(song['description']) > 4400:
        raise ValueError('YouTube metadata too long')
    song['lyrics'] = normalize_lyrics(song['lyrics'])
    if 'dudi dudi dam dam dudi dudi dam' not in song['lyrics'].lower():
        raise ValueError('Dudi refrain required')
    if not 480 <= song.get('duration', 0) <= 720:
        raise ValueError('Song must be 480-720 seconds')
    if 'tags' in song and (not isinstance(song['tags'], list) or
            not all(isinstance(tag, str) and 0 < len(tag.strip()) <= 40 for tag in song['tags'])):
        raise ValueError('Invalid song tags')
    if 'visual_mood' in song and song['visual_mood'] not in ('romance', 'heartbreak', 'healing'):
        raise ValueError('Invalid visual mood')
    if 'thumbnail_text' in song and not re.fullmatch(r'[A-Za-z0-9 !?]{3,26}', song['thumbnail_text']):
        raise ValueError('Invalid thumbnail hook')
    for field in ('background_prompt', 'thumbnail_prompt'):
        if field in song and (not isinstance(song[field], str) or not 40 <= len(song[field]) <= 380):
            raise ValueError('Invalid image prompt')
    from kids_rhymes import validate_storyboard
    validate_storyboard(song)
    return song


from kids_rhymes import make_song, upload_description, metadata_tags


def duration(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=nw=1:nk=1', str(path)], text=True))


def validate_duration(seconds):
    if not 480 <= seconds <= 720:
        raise ValueError('Measured song/video duration outside 8-12 minutes')


def render(root):
    from kids_rhymes import render_video
    render_video(root)


def youtube_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    client = build('youtube', 'v3', credentials=Credentials.from_authorized_user_info(
        json.loads(required('YOUTUBE_TOKEN_JSON'))), cache_discovery=False)
    items = client.channels().list(part='id,snippet', mine=True).execute().get('items', [])
    expected = required('EXPECTED_CHANNEL_ID')
    if len(items) != 1 or items[0]['id'] != expected:
        raise RuntimeError('Wrong YouTube channel; select Dudi Dam TV')
    return client


def publish(client, root, song, state, save):
    from googleapiclient.http import MediaFileUpload
    if not state.get('video_id'):
        if state.get('upload_started'):
            raise RuntimeError('Ambiguous upload; reconcile YouTube before retry to avoid duplicates')
        state['upload_description'] = upload_description(song)
        state['upload_started'] = True
        save()
        request = client.videos().insert(part='snippet,status', body={
            'snippet': {'title': song['title'], 'description': state['upload_description'],
                'categoryId': '10', 'defaultLanguage': 'en', 'defaultAudioLanguage': 'en',
                'tags': metadata_tags(song)},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': True,
                       'containsSyntheticMedia': True}},
            media_body=MediaFileUpload(str(root/'video.mp4'), resumable=True, chunksize=8*1024*1024))
        result = None
        while result is None:
            _, result = request.next_chunk(num_retries=5)
        state['video_id'] = result['id']
        save()
    if not state.get('thumbnail_uploaded'):
        client.thumbnails().set(videoId=state['video_id'],
            media_body=MediaFileUpload(str(root/'thumbnail.jpg'))).execute()
        state['thumbnail_uploaded'] = True
        save()
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        items = client.videos().list(part='snippet,status,processingDetails,contentDetails',
                                    id=state['video_id']).execute().get('items', [])
        if not items:
            raise RuntimeError('Uploaded video unavailable')
        video = items[0]
        if video['snippet']['channelId'] != required('EXPECTED_CHANNEL_ID'):
            raise RuntimeError('Uploaded channel mismatch')
        status = video['status']
        if status.get('uploadStatus') in ('failed', 'rejected', 'deleted'):
            raise RuntimeError('YouTube rejected upload')
        if status.get('privacyStatus') != 'public':
            raise RuntimeError('YouTube did not retain public visibility; inspect project/channel restrictions')
        if status.get('uploadStatus') == 'processed' and video.get('contentDetails', {}).get('definition') == 'hd':
            state['phase'] = 'published'
            save()
            return
        time.sleep(20)
    raise TimeoutError('HD processing pending; rerun same run ID')


def run(run_id, defer_drive_cleanup=False):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run ID')
    root = Path('output')/run_id
    root.mkdir(parents=True, exist_ok=True)
    store = Store()
    client = youtube_client()  # Verify accounts before expensive generation.
    key = f'runs/{run_id}/state.json'
    state = store.load(key, {})
    save = lambda: store.save(key, state)
    history = store.load('history.json', [])
    if state.get('phase') == 'published':
        if not any(h['run'] == run_id for h in history):
            history.append({'run': run_id, 'title': state['song']['title'],
                            'hash': state['hash'], 'video_id': state['video_id']})
            store.save('history.json', history)
        if not defer_drive_cleanup:
            from cleanup_drive import cleanup
            cleanup(store, client, run_id, state)
        print('Already published: ' + state['video_id'])
        return
    if not state.get('song'):
        day = dt.datetime.now(ZoneInfo('Asia/Dhaka')).date().isoformat()
        song = (validate_song(json.loads((root/'song.json').read_text()))
                if (root/'song.json').exists() else make_song(day, history, root/'song-draft.json', generation_id=run_id))
        digest = hashlib.sha256(song['lyrics'].encode()).hexdigest()
        if song_duplicate_reason(song, history, run_id):
            raise DuplicateSongError()
        state.update(song=song, hash=digest)
        save()
    song = validate_song(state['song'])
    (root/'song.json').write_text(json.dumps(song, ensure_ascii=False, indent=2))
    if not (root/'song.wav').exists():
        fid = store.find(f'runs/{run_id}/song.wav')
        if fid:
            store.download(fid, root/'song.wav')
        else:
            from music_cpu import generate
            generate(song, root/'song.wav', state, save)
    validate_duration(duration(root/'song.wav'))
    if not state.get('video_id'):
        store.upload(root/'song.wav', f'runs/{run_id}/song.wav')
        if not (root/'video.mp4').exists():
            from song_images import generate_song_images
            generate_song_images(root, song)
            render(root)
        validate_duration(duration(root/'video.mp4'))
        import tarfile
        with tarfile.open(root/'storyboard.tar.gz', 'w:gz') as archive:
            for path in sorted(root.glob('scene-*-source.png')) + sorted(root.glob('image-manifest-*.json')):
                archive.add(path, arcname=path.name)
        for name in ('storyboard.tar.gz', 'song.json', 'video.mp4', 'thumbnail.jpg', 'background-source.png', 'thumbnail-source.png', 'image-manifest.json'):
            if (root/name).exists():
                store.upload(root/name, f'runs/{run_id}/{name}')
    elif not (root/'thumbnail.jpg').exists():
        store.download(store.find(f'runs/{run_id}/thumbnail.jpg'), root/'thumbnail.jpg')
    publish(client, root, song, state, save)
    if not any(h['run'] == run_id for h in history):
        history.append({'run': run_id, 'title': song['title'], 'hash': state['hash'], 'video_id': state['video_id']})
        store.save('history.json', history)
    if not defer_drive_cleanup:
        from cleanup_drive import cleanup
        cleanup(store, client, run_id, state)
    print(json.dumps({'phase': state['phase'], 'video_id': state['video_id']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--defer-drive-cleanup', action='store_true',
                        help='Leave verified media cleanup to the separate workflow job')
    args = parser.parse_args()
    try:
        run(args.run_id, defer_drive_cleanup=args.defer_drive_cleanup)
    except Exception as error:
        # Avoid leaking OAuth/API credentials through raw exception response bodies.
        print(pipeline_failure_message(error))
        raise SystemExit(1)
