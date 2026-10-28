import copy
import hashlib
import types
import unittest
from unittest.mock import Mock, patch

from cleanup_drive import cleanup
from pipeline import metadata_tags, upload_description


class DriveCleanupTests(unittest.TestCase):
    def setUp(self):
        self.run_id = 'original-hindi-20261026-artwork-01'
        self.key = f'runs/{self.run_id}/video.mp4'
        self.song = {'title': 'नई सुबह', 'description': 'A hopeful Hindi song', 'tags': ['Hindi music']}
        self.state = {'phase': 'published', 'video_id': 'video', 'thumbnail_uploaded': True, 'song': self.song}
        self.video = {'id': 'video', 'snippet': {'channelId': 'channel', 'title': self.song['title'],
            'description': upload_description(self.song),
            'tags': metadata_tags(self.song)}, 'status': {'privacyStatus': 'public', 'uploadStatus': 'processed'},
            'processingDetails': {'processingStatus': 'succeeded'}, 'contentDetails': {'definition': 'hd'}}
        self.client = Mock()
        self.client.videos().list().execute.return_value = {'items': [self.video]}
        self.store = Mock(folder='folder')
        self.journal = {'run': self.run_id, 'video_id': 'video', 'files': [{'id': 'file', 'name': 'video.mp4'}], 'deleted': []}
        self.store.load.return_value = self.journal
        self.remote = {'id': 'file', 'name': self.key.replace('/', '__'), 'parents': ['folder'],
            'appProperties': {'workflow_key': hashlib.sha256(self.key.encode()).hexdigest()}, 'mimeType': 'video/mp4'}
        self.store.client.files().get().execute.return_value = self.remote
        self.environment = patch.dict('os.environ', {'EXPECTED_CHANNEL_ID': 'channel'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_failed_unpublished_or_missing_thumbnail_never_deletes(self):
        for field, value in [('phase', 'generating'), ('video_id', ''), ('thumbnail_uploaded', False)]:
            with self.assertRaises(RuntimeError):
                cleanup(self.store, self.client, self.run_id, dict(self.state, **{field: value}))
        self.store.client.files().delete.assert_not_called()

    def test_fresh_remote_verification_requires_public_hd_success_and_matching_metadata(self):
        original = copy.deepcopy(self.video)
        cases = [('status', 'privacyStatus', 'private'), ('status', 'uploadStatus', 'failed'),
                 ('contentDetails', 'definition', 'sd'), ('processingDetails', 'processingStatus', 'processing'),
                 ('snippet', 'title', 'Wrong title'), ('snippet', 'channelId', 'other'),
                 ('snippet', 'description', 'changed'), ('snippet', 'tags', ['other'])]
        for section, field, value in cases:
            self.video.clear()
            self.video.update(copy.deepcopy(original))
            self.video[section][field] = value
            with self.assertRaises(RuntimeError):
                cleanup(self.store, self.client, self.run_id, self.state)
        self.store.client.files().delete.assert_not_called()

    def test_deletes_only_exact_media_id_and_repeat_is_idempotent(self):
        cleanup(self.store, self.client, self.run_id, self.state)
        self.store.client.files().delete.assert_called_once_with(fileId='file')
        self.assertTrue(self.journal['complete'])
        cleanup(self.store, self.client, self.run_id, self.state)
        self.store.client.files().delete.assert_called_once_with(fileId='file')

    def test_rejects_other_folder_hash_name_or_folder_type(self):
        original = copy.deepcopy(self.remote)
        for field, value in [('parents', ['other']), ('name', 'unrelated.mp4'),
                             ('appProperties', {'workflow_key': 'wrong'}),
                             ('mimeType', 'application/vnd.google-apps.folder')]:
            self.remote.clear()
            self.remote.update(copy.deepcopy(original))
            self.remote[field] = value
            with self.assertRaises(RuntimeError):
                cleanup(self.store, self.client, self.run_id, self.state)
        self.store.client.files().delete.assert_not_called()

    def test_preserves_state_history_lyrics_and_unrelated_files(self):
        self.store.load.return_value = None
        self.store.find.side_effect = lambda key: 'file' if key == self.key else None
        cleanup(self.store, self.client, self.run_id, self.state)
        keys = [call.args[0] for call in self.store.find.call_args_list]
        self.assertNotIn(f'runs/{self.run_id}/state.json', keys)
        self.assertNotIn(f'runs/{self.run_id}/song.json', keys)
        self.assertNotIn('history.json', keys)
        self.assertNotIn(f'runs/{self.run_id}/image-manifest.json', keys)
        calls = [call[0] for call in self.store.mock_calls]
        self.assertLess(calls.index('save'), calls.index('client.files().delete'))

    def test_deleted_before_checkpoint_is_safe_to_resume(self):
        error = RuntimeError('not found')
        error.resp = types.SimpleNamespace(status=404)
        self.store.client.files().get().execute.side_effect = error
        cleanup(self.store, self.client, self.run_id, self.state)
        self.assertEqual(self.journal['deleted'], ['file'])
        self.store.client.files().delete.assert_not_called()

    def test_delete_failure_preserves_checkpoint_for_retry(self):
        self.store.client.files().delete().execute.side_effect = RuntimeError('permission denied')
        with self.assertRaises(RuntimeError):
            cleanup(self.store, self.client, self.run_id, self.state)
        self.assertEqual(self.journal['deleted'], [])
        self.assertNotIn('complete', self.journal)


if __name__ == '__main__':
    unittest.main()
