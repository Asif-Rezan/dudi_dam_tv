import copy
import datetime as dt
import os
import unittest
from unittest.mock import patch
from upload_settings import load_settings, upload_body, verified_phase

class UploadSettingsTests(unittest.TestCase):
    def test_public_and_disclosures(self):
        with patch.dict(os.environ,{},clear=True):
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
        for value in ('','2020-01-01T00:00:00Z','2030-01-01T18:00:00'):
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
