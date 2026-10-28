"""Explicit, validated YouTube upload settings, checkpointed before upload."""
import datetime as dt
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

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
    if settings['mode'] == 'scheduled' and not settings.get('publish_at'):
        if settings.get('schedule_policy') != 'new_york_6am_after_72h':
            raise ValueError('Automatic schedule policy missing')
    elif settings['mode'] == 'scheduled':
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
    if settings['mode']=='scheduled' and settings.get('publish_at'):
        status['publishAt'] = settings['publish_at']
    return dict(snippet=dict(title=song['title'],description=description,tags=tags,
        categoryId=settings['category_id'],defaultLanguage=settings['language'],defaultAudioLanguage=settings['audio_language']),
        status=status, paidProductPlacementDetails=dict(hasPaidProductPlacement=settings['paid_product_placement']))


def new_york_publish_time(upload_finished):
    """First 06:00 America/New_York slot at least 72 elapsed hours after upload."""
    if upload_finished.tzinfo is None:
        raise ValueError('Upload completion must include a timezone')
    earliest = upload_finished.astimezone(dt.timezone.utc) + dt.timedelta(hours=72)
    zone = ZoneInfo('America/New_York')
    local_day = earliest.astimezone(zone).date()
    candidate = dt.datetime.combine(local_day, dt.time(6), tzinfo=zone)
    if candidate.astimezone(dt.timezone.utc) < earliest:
        candidate = dt.datetime.combine(local_day+dt.timedelta(days=1),dt.time(6),tzinfo=zone)
    return candidate.astimezone(dt.timezone.utc).isoformat().replace('+00:00','Z')


def schedule_uploaded_video(client, state, save, now=None):
    """Upload privately, then set a stable post-upload schedule; retries reuse it."""
    settings = state['upload_settings']
    if settings['mode'] != 'scheduled' or settings.get('publish_at') or state.get('schedule_configured'):
        return
    if settings.get('schedule_policy') != 'new_york_6am_after_72h':
        raise ValueError('Unsupported automatic schedule policy')
    if not state.get('video_id'):
        raise ValueError('Upload must complete before scheduling')
    current = now or dt.datetime.now(dt.timezone.utc)
    # When recovering an upload checkpoint without a timestamp, using now is a
    # conservative upper bound: it can delay release, never shorten the 72h wait.
    if not state.get('upload_completed_at'):
        state['upload_completed_at'] = current.isoformat()
    if not state.get('schedule_target'):
        finished = dt.datetime.fromisoformat(state['upload_completed_at'].replace('Z','+00:00'))
        state['schedule_target'] = new_york_publish_time(finished)
        state['upload_body']['status']['publishAt'] = state['schedule_target']
        save()  # Freeze the target before mutating YouTube so retries cannot drift.
    expected = state['schedule_target']
    if dt.datetime.fromisoformat(expected.replace('Z','+00:00')) <= current:
        raise RuntimeError('Unconfirmed schedule is in the past; reconcile the existing video')
    client.videos().update(part='status', body={'id':state['video_id'],
        'status':state['upload_body']['status']}).execute()
    state['schedule_configured'] = True
    save()


def ensure_synthetic_disclosure(client, video, state, save):
    """Submit the required disclosure on the existing upload, preserving visibility.

    Some API responses omit this writeable field. Record a successful explicit
    write for that video; never treat an explicit false value as verified.
    """
    if state['upload_body']['status'].get('containsSyntheticMedia') is not True:
        raise ValueError('AI disclosure is required')
    status=video.get('status',{})
    if status.get('containsSyntheticMedia') is True:
        return
    receipt=state.get('synthetic_disclosure_receipt',{})
    if ('containsSyntheticMedia' not in status and receipt.get('video_id')==state['video_id']
            and receipt.get('accepted') is True):
        return
    if video.get('id')!=state['video_id']:
        raise RuntimeError('Uploaded video unavailable')
    # Status updates replace mutable properties: preserve the live visibility,
    # schedule and other settings instead of restoring an old private status.
    fields=('privacyStatus','publishAt','license','embeddable','publicStatsViewable','selfDeclaredMadeForKids')
    update={field:status[field] for field in fields if field in status}
    update['containsSyntheticMedia']=True
    response=client.videos().update(part='status',body={'id':state['video_id'],'status':update}).execute()
    returned=response.get('status',{})
    print(json.dumps({'check':'AI disclosure update','readback_present':'containsSyntheticMedia' in returned,
                      'readback_value':returned.get('containsSyntheticMedia')}),flush=True)
    if response.get('id')!=state['video_id'] or returned.get('containsSyntheticMedia') is False:
        raise RuntimeError('Uploaded setting mismatch: containsSyntheticMedia')
    state['synthetic_disclosure_receipt']={'video_id':state['video_id'],'accepted':True,
        'accepted_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    save()


def verified_phase(video, body, channel_id, disclosure_receipt=None):
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
        if (field=='containsSyntheticMedia' and field not in status
                and body['status'][field] is True and disclosure_receipt
                and disclosure_receipt.get('accepted') is True
                and disclosure_receipt.get('video_id')==video.get('id')):
            continue
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
