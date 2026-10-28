"""Local OAuth setup; tokens pass directly to GitHub CLI stdin."""
import argparse
import json
import subprocess
import shutil
import os
from pathlib import Path

REPO = 'Asif-Rezan/Heart-and-Mind'
SCOPES = {
    'youtube': ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly'],
    'drive': ['https://www.googleapis.com/auth/drive.file'],
}


def secret(name, value):
    if shutil.which('gh'):
        subprocess.run(['gh', 'secret', 'set', name, '--repo', REPO], input=value,
                       text=True, check=True, capture_output=True)
    else:
        directory = Path('.credentials')
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        path = directory/name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(value)
        print('Prepared encrypted-repository-secret input locally: ' + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('account', choices=SCOPES)
    parser.add_argument('--client', default='client_secrets.json')
    parser.add_argument('--channel-id', help='Required for YouTube; copy Heart and Mind channel ID from Studio')
    args = parser.parse_args()
    if args.account == 'youtube' and not args.channel_id:
        parser.error('--channel-id is required to prevent selecting another channel')
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    config = json.loads(Path(args.client).read_text())
    if 'installed' not in config:
        raise ValueError('Use Desktop OAuth client JSON from the Production project')
    email = 'asifrezan@gmail.com' if args.account == 'youtube' else 'asifrezanit@gmail.com'
    flow = InstalledAppFlow.from_client_config(config, SCOPES[args.account], autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host='127.0.0.1', port=0, prompt='consent',
        access_type='offline', login_hint=email, timeout_seconds=1800, open_browser=False)
    if not credentials.refresh_token:
        raise RuntimeError('Offline refresh token missing')
    if not set(SCOPES[args.account]).issubset(set(credentials.granted_scopes or credentials.scopes or [])):
        raise RuntimeError('Required scopes not granted')
    if args.account == 'youtube':
        api = build('youtube', 'v3', credentials=credentials, cache_discovery=False)
        channels = api.channels().list(part='id,snippet', mine=True).execute().get('items', [])
        if len(channels) != 1 or channels[0]['id'] != args.channel_id:
            raise RuntimeError('Wrong channel selected; no secrets changed')
        secret('YOUTUBE_TOKEN_JSON', credentials.to_json())
        secret('EXPECTED_CHANNEL_ID', args.channel_id)
        print('Verified channel: ' + channels[0]['snippet']['title'])
    else:
        api = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        if api.about().get(fields='user(emailAddress)').execute()['user']['emailAddress'].lower() != email:
            raise RuntimeError('Wrong Drive account; no folder created')
        folders = api.files().list(q="trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has { key='heart_and_mind_root' and value='v1' }", fields='files(id)').execute()['files']
        if len(folders) > 1:
            raise RuntimeError('Multiple project folders; reconcile manually')
        folder = folders[0] if folders else api.files().create(body={
            'name': 'Heart and Mind - Hindi Music Automation',
            'mimeType': 'application/vnd.google-apps.folder',
            'appProperties': {'heart_and_mind_root': 'v1'}}, fields='id').execute()
        secret('DRIVE_TOKEN_JSON', credentials.to_json())
        secret('DRIVE_FOLDER_ID', folder['id'])
        print('Dedicated Drive folder configured for ' + email)
    print('Credentials prepared securely; no tokens printed. If GitHub CLI is unavailable, save .credentials inputs as repository Actions secrets.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Setup failed: ' + type(error).__name__ + '. No credentials printed.')
        raise SystemExit(1)
