"""Explicit, validated YouTube upload settings, checkpointed before upload."""
import datetime as dt
import json
import os
from pathlib import Path
import re

SETTINGS = Path(__file__).with_name('upload_settings.json')

def load_settings(now=None):
    settings = json.loads(SETTINGS.read_text())
    for env, field in [('UPLOAD_MODE','mode'),('PUBLISH_AT','publish_at'),('VIDEO_LANGUAGE','language'),
                       ('AUDIO_LANGUAGE','audio_language'),('VIDEO_CATEGORY_ID','category_id')]:
        if os.getenv(env):
            settings[field] = os.environ[env]
    if settings['mode'] not in ('public', 'scheduled'):
        raise ValueError('Upload mode must be public or scheduled')
    for field in ('language','audio_language'):
        if not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', settings[field]):
            raise ValueError('Invalid language code')
    if not re.fullmatch(r'[1-9][0-9]*', settings['category_id']):
        raise ValueError('Invalid YouTube category ID')
    for field in ('made_for_kids','contains_synthetic_media','embeddable','public_stats_viewable',
                  'notify_subscribers','paid_product_placement'):
        if type(settings[field]) is not bool:
            raise ValueError('Expected boolean setting: ' + field)
    if not settings['made_for_kids'] or not settings['contains_synthetic_media']:
        raise ValueError('Kids and AI disclosures are required for this pipeline')
    if settings['license'] not in ('youtube','creativeCommon'):
        raise ValueError('Invalid license')
    if settings['mode'] == 'scheduled':
        when = dt.datetime.fromisoformat((settings.get('publish_at') or '').replace('Z','+00:00'))
        if when.tzinfo is None or when <= (now or dt.datetime.now(dt.timezone.utc)):
            raise ValueError('Scheduled publication needs a future ISO timestamp with timezone')
        settings['publish_at'] = when.astimezone(dt.timezone.utc).isoformat().replace('+00:00','Z')
    elif settings.get('publish_at'):
        raise ValueError('publish_at must be empty for public mode')
    return settings


def upload_body(song, description, tags, settings):
    status = dict(privacyStatus='private' if settings['mode']=='scheduled' else 'public',
        selfDeclaredMadeForKids=settings['made_for_kids'], containsSyntheticMedia=settings['contains_synthetic_media'],
        license=settings['license'], embeddable=settings['embeddable'], publicStatsViewable=settings['public_stats_viewable'])
    if settings['mode']=='scheduled':
        status['publishAt'] = settings['publish_at']
    return dict(snippet=dict(title=song['title'],description=description,tags=tags,
        categoryId=settings['category_id'],defaultLanguage=settings['language'],defaultAudioLanguage=settings['audio_language']),
        status=status, paidProductPlacementDetails=dict(hasPaidProductPlacement=settings['paid_product_placement']))


def verified_phase(video, body, channel_id):
    """Return a terminal phase only for matching remote metadata and processed HD."""
    snippet, status = video.get('snippet',{}), video.get('status',{})
    if snippet.get('channelId') != channel_id:
        raise RuntimeError('Uploaded channel mismatch')
    if status.get('uploadStatus') in ('failed','rejected','deleted'):
        raise RuntimeError('YouTube rejected upload')
    for field in ('title','description','categoryId','defaultLanguage','defaultAudioLanguage'):
        if snippet.get(field) != body['snippet'][field]:
            raise RuntimeError('Uploaded metadata mismatch: ' + field)
    if set(snippet.get('tags',[])) != set(body['snippet']['tags']):
        raise RuntimeError('Uploaded tags mismatch')
    for field in ('selfDeclaredMadeForKids','containsSyntheticMedia','license','embeddable','publicStatsViewable'):
        if status.get(field) != body['status'][field]:
            raise RuntimeError('Uploaded setting mismatch: ' + field)
    if video.get('paidProductPlacementDetails',{}).get('hasPaidProductPlacement',False) != body['paidProductPlacementDetails']['hasPaidProductPlacement']:
        raise RuntimeError('Paid placement disclosure mismatch')
    if 'publishAt' in body['status'] and status.get('privacyStatus') == 'private':
        wanted=dt.datetime.fromisoformat(body['status']['publishAt'].replace('Z','+00:00'))
        got=dt.datetime.fromisoformat(status.get('publishAt','').replace('Z','+00:00'))
        if got!=wanted:
            raise RuntimeError('Scheduled time mismatch')
        phase='scheduled'
    elif status.get('privacyStatus')=='public':
        phase='published'
    else:
        raise RuntimeError('YouTube did not retain requested visibility')
    if status.get('uploadStatus')=='processed' and video.get('contentDetails',{}).get('definition')=='hd' and video.get('processingDetails',{}).get('processingStatus')=='succeeded':
        return phase
    return None
