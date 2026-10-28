"""Permanently remove only one verified published song's temporary Drive media."""
import argparse
import hashlib
import json
import re

from storage import Store, drive_retry, required

MEDIA = ('song.wav', 'video.mp4', 'thumbnail.jpg', 'background-source.png',
         'thumbnail-source.png', 'cover.png')


def verify_public(client, state):
    from pipeline import metadata_tags, upload_description
    if state.get('phase') != 'published' or not state.get('video_id') or state.get('thumbnail_uploaded') is not True:
        raise RuntimeError('Published video and uploaded thumbnail required before cleanup')
    items = client.videos().list(part='snippet,status,processingDetails,contentDetails',
                                id=state['video_id']).execute().get('items', [])
    if len(items) != 1:
        raise RuntimeError('Published video unavailable; preserve Drive media')
    video = items[0]
    snippet, status = video.get('snippet', {}), video.get('status', {})
    song = state['song']
    description = state.get('upload_description', upload_description(song))
    if (video.get('id') != state['video_id'] or snippet.get('channelId') != required('EXPECTED_CHANNEL_ID')
            or snippet.get('title') != song['title'] or snippet.get('description') != description
            or set(snippet.get('tags', [])) != set(metadata_tags(song))
            or status.get('privacyStatus') != 'public' or status.get('uploadStatus') != 'processed'
            or video.get('processingDetails', {}).get('processingStatus') != 'succeeded'
            or video.get('contentDetails', {}).get('definition') != 'hd'):
        raise RuntimeError('Public HD video or metadata verification failed; preserve Drive media')


def cleanup(store, client, run_id, state):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run ID')
    verify_public(client, state)  # Fresh YouTube proof, including on cleanup-only retries.
    key = f'runs/{run_id}/cleanup.json'
    journal = store.load(key, None)
    if journal is None:
        files = []
        for name in MEDIA:
            media_key = f'runs/{run_id}/{name}'
            file_id = store.find(media_key)
            if file_id:
                files.append({'id': file_id, 'name': name})
        journal = {'run': run_id, 'video_id': state['video_id'], 'files': files, 'deleted': []}
        store.save(key, journal)  # Durable exact-ID manifest before any deletion.
    if journal.get('run') != run_id or journal.get('video_id') != state['video_id']:
        raise RuntimeError('Cleanup journal identity mismatch')
    for entry in journal['files']:
        file_id, name = entry['id'], entry['name']
        if name not in MEDIA:
            raise RuntimeError('Unsafe cleanup manifest entry')
        if file_id in journal['deleted']:
            continue
        media_key = f'runs/{run_id}/{name}'
        try:
            remote = drive_retry(lambda: store.client.files().get(fileId=file_id,
                fields='id,name,parents,appProperties,mimeType,trashed').execute())
            if (remote.get('id') != file_id or remote.get('name') != media_key.replace('/', '__')
                    or store.folder not in remote.get('parents', [])
                    or remote.get('appProperties', {}).get('workflow_key') != hashlib.sha256(media_key.encode()).hexdigest()
                    or remote.get('mimeType') == 'application/vnd.google-apps.folder'):
                raise RuntimeError('Unsafe cleanup target rejected')
            store.check_private(file_id)
            drive_retry(lambda: store.client.files().delete(fileId=file_id).execute())
        except Exception as error:
            if getattr(getattr(error, 'resp', None), 'status', None) != 404:
                raise
            # The previous attempt may have deleted the file before saving its checkpoint.
        journal['deleted'].append(file_id)
        store.save(key, journal)
    journal['complete'] = True
    store.save(key, journal)
    print(json.dumps({'run': run_id, 'video_id': state['video_id'],
                      'cleanup_complete': True, 'deleted_media': len(journal['deleted'])}), flush=True)
    return journal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', args.run_id):
        raise ValueError('Invalid run ID')
    from pipeline import youtube_client
    store = Store()
    state = store.load(f'runs/{args.run_id}/state.json', {})
    cleanup(store, youtube_client(), args.run_id, state)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Drive cleanup failed: ' + type(error).__name__ + '. Media and cleanup journal are retained for retry.')
        raise SystemExit(1)
