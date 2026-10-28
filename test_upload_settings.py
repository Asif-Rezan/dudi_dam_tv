import copy
import datetime as dt
import os
import unittest
from unittest.mock import patch, Mock
from upload_settings import load_settings, upload_body, verified_phase, new_york_publish_time, schedule_uploaded_video

class UploadSettingsTests(unittest.TestCase):
    def test_public_and_disclosures(self):
        with patch.dict(os.environ,{'UPLOAD_MODE':'public'},clear=True):
            settings=load_settings()
        body=upload_body({'title':'Dudi'},'Description',['kids'],settings)
        self.assertEqual(body['status']['privacyStatus'],'public')
        self.assertTrue(body['status']['selfDeclaredMadeForKids'])
        self.assertTrue(body['status']['containsSyntheticMedia'])
        self.assertEqual(body['snippet']['categoryId'],'10')
        self.assertNotIn('publishAt',body['status'])

    def test_schedule_and_timezone(self):
        with patch.dict(os.environ,{'UPLOAD_MODE':'scheduled','PUBLISH_AT':'2030-01-01T18:00:00+06:00'},clear=True):
            settings=load_settings(now=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc))
        body=upload_body({'title':'Dudi'},'Description',[],settings)
        self.assertEqual(body['status']['privacyStatus'],'private')
        self.assertEqual(body['status']['publishAt'],'2030-01-01T12:00:00Z')

    def test_reject_bad_schedule(self):
        for value in ('2020-01-01T00:00:00Z','2030-01-01T18:00:00'):
            with patch.dict(os.environ,{'UPLOAD_MODE':'scheduled','PUBLISH_AT':value},clear=True),self.assertRaises(ValueError):
                load_settings()

    def test_verify_public_and_scheduled_and_mismatches(self):
        for mode in ('public','scheduled'):
            env={'UPLOAD_MODE':mode}
            if mode=='scheduled': env['PUBLISH_AT']='2030-01-01T12:00:00Z'
            with patch.dict(os.environ,env,clear=True): settings=load_settings()
            body=upload_body({'title':'Dudi'},'Description',['kids'],settings)
            video=copy.deepcopy(body)
            video['snippet']['channelId']='right-channel'
            video['status']['uploadStatus']='processed'
            video['processingDetails']={'processingStatus':'succeeded'}
            video['contentDetails']={'definition':'hd'}
            self.assertEqual(verified_phase(video,body,'right-channel'),'published' if mode=='public' else 'scheduled')
            with self.assertRaises(RuntimeError): verified_phase(video,body,'wrong-channel')
            video['status']['containsSyntheticMedia']=False
            with self.assertRaises(RuntimeError): verified_phase(video,body,'right-channel')

    def test_scheduled_video_can_become_public(self):
        with patch.dict(os.environ,{'UPLOAD_MODE':'scheduled','PUBLISH_AT':'2030-01-01T12:00:00Z'},clear=True): settings=load_settings()
        body=upload_body({'title':'Dudi'},'Description',[],settings)
        video=copy.deepcopy(body)
        video['snippet']['channelId']='channel'
        video['status'].update(privacyStatus='public',uploadStatus='processed')
        video['status'].pop('publishAt')
        video['processingDetails']={'processingStatus':'succeeded'}
        video['contentDetails']={'definition':'hd'}
        self.assertEqual(verified_phase(video,body,'channel'),'published')

    def test_automatic_schedule_is_default_and_initial_upload_is_private(self):
        with patch.dict(os.environ,{},clear=True):
            settings=load_settings()
        self.assertEqual(settings['mode'],'scheduled')
        self.assertIsNone(settings['publish_at'])
        body=upload_body({'title':'Dudi'},'description',[],settings)
        self.assertEqual(body['status']['privacyStatus'],'private')
        self.assertNotIn('publishAt',body['status'])

    def test_new_york_time_boundaries_and_daylight_saving(self):
        from zoneinfo import ZoneInfo
        for finished, expected in [
            ('2026-10-28T08:00:00Z','2026-10-31T10:00:00Z'),
            ('2026-10-28T10:00:00Z','2026-10-31T10:00:00Z'),
            ('2026-10-28T10:00:01Z','2026-11-01T11:00:00Z'),
            ('2026-10-30T10:30:00Z','2026-11-02T11:00:00Z'),
            ('2027-03-12T10:30:00Z','2027-03-16T10:00:00Z'),
            ('2027-01-05T20:00:00Z','2027-01-09T11:00:00Z')]:
            end=dt.datetime.fromisoformat(finished.replace('Z','+00:00'))
            result=new_york_publish_time(end)
            self.assertEqual(result,expected)
            when=dt.datetime.fromisoformat(result.replace('Z','+00:00'))
            self.assertGreaterEqual((when-end).total_seconds(),72*3600)
            self.assertEqual(when.astimezone(ZoneInfo('America/New_York')).hour,6)

    def test_schedule_after_upload_freezes_target_across_update_retry(self):
        with patch.dict(os.environ,{},clear=True): settings=load_settings()
        state={'video_id':'video','upload_settings':settings,
            'upload_completed_at':'2026-10-28T12:00:00Z',
            'upload_body':upload_body({'title':'Dudi'},'description',[],settings)}
        client,save=Mock(),Mock()
        client.videos().update().execute.side_effect=[RuntimeError('interrupted'),{}]
        now=dt.datetime(2026,10,28,12,tzinfo=dt.timezone.utc)
        with self.assertRaises(RuntimeError): schedule_uploaded_video(client,state,save,now)
        self.assertFalse(state.get('schedule_configured',False))
        target=state['schedule_target']
        schedule_uploaded_video(client,state,save,now+dt.timedelta(hours=2))
        self.assertEqual(state['schedule_target'],target)
        self.assertTrue(state['schedule_configured'])
        call=client.videos().update.call_args.kwargs
        self.assertEqual(call['body']['status']['publishAt'],target)
        self.assertEqual(call['body']['status']['privacyStatus'],'private')
        count=client.videos().update.call_count
        schedule_uploaded_video(client,state,save,now+dt.timedelta(hours=3))
        self.assertEqual(client.videos().update.call_count,count)
