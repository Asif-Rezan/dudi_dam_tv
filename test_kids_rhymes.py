import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import kids_rhymes as kids
from pipeline import validate_song, validate_duration
from song_images import image_plan, generate_song_images

class KidsTests(unittest.TestCase):
    def setUp(self):
        def written(day,identity,seconds,history,draft_path=None):
            return dict(writer_version='qwen-kids-original-v1',outline=dict(title='Duck and Bunny Find a Rainbow',
                description='A new playful story about two kind animal friends discovering a garden rainbow.',
                story_summary='Duck and bunny follow a bright rainbow through the garden.'),
                sections=[[dict(lyric=f'Friendly ducks discover garden number {i}',visual=f'Duckling and bunny exploring flower patch {i}')
                           for i in range((seconds+9)//10)]])
        model=patch('kids_rhymes.write_rhyme',side_effect=written)
        model.start()
        self.addCleanup(model.stop)

    def song(self, seconds=600):
        with patch.dict(os.environ, VIDEO_DURATION_SECONDS=str(seconds)):
            return kids.make_song('2026-10-28', [], generation_id='test')

    def test_duration_and_storyboard(self):
        for seconds in (480,600,720):
            song = validate_song(self.song(seconds))
            self.assertEqual(len(song['scenes']),seconds//5)
            self.assertEqual(song['vocal_gender'],'female')
            validate_duration(seconds)
        for seconds in (479,721):
            with self.assertRaises(ValueError):
                self.song(seconds)
            with self.assertRaises(ValueError):
                validate_duration(seconds)

    def test_mismatched_storyboard_rejected(self):
        song = self.song()
        song['scenes'][3]['start'] += 1
        with self.assertRaises(ValueError):
            validate_song(song)
        song=self.song()
        song['lyrics'] += '\nextra'
        with self.assertRaises(ValueError):
            validate_song(song)

    def test_unique_scene_seeds_and_complete_shards(self):
        plans=image_plan(self.song(720))
        self.assertEqual(len(plans),145)
        self.assertEqual(len({p['seed'] for p in plans}),145)
        self.assertEqual(len({p['kind'] for p in plans}),145)
        def fake_generate(prompt,target,**kwargs):
            Image.new('RGB',(32,18),'yellow').save(target)
        with tempfile.TemporaryDirectory() as tmp, patch('image_cpu.generate',side_effect=fake_generate) as generate:
            for shard in range(16):
                with patch.dict(os.environ, IMAGE_SHARD=str(shard),IMAGE_SHARDS='16'):
                    generate_song_images(tmp,self.song(720))
                    generate_song_images(tmp,self.song(720))
            self.assertEqual(generate.call_count,145)
            self.assertEqual(len(list(Path(tmp).glob('*-source.png'))),145)

    def test_render_rejects_missing_scene_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); song=self.song(480)
            (root/'song.json').write_text(json.dumps(song))
            (root/'song.wav').write_bytes(b'fixture')
            Image.new('RGB',(32,18),'pink').save(root/'thumbnail-source.png')
            with patch('pipeline.duration',return_value=480), patch('motion_video.run_ffmpeg') as run:
                with self.assertRaises(FileNotFoundError):
                    kids.render_video(root)
                run.assert_not_called()

if __name__ == '__main__':
    unittest.main()
