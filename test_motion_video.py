import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from motion_video import render_scenes, render_identity, render_is_current, scene_filter, FPS

class MotionTests(unittest.TestCase):
    def test_five_second_clips_transition_and_sound_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            scenes=[{'index':i} for i in range(3)]
            for scene in scenes:
                Image.new('RGB',(32,18),'yellow').save(root/f"scene-{scene['index']:03d}-source.png")
            with patch('motion_video.run_ffmpeg') as run:
                listing=render_scenes(root,scenes,320,180)
            commands=[c.args[0] for c in run.call_args_list]
            clips=[cmd for cmd in commands if '-filter_complex' in cmd]
            self.assertEqual(len(clips),3)
            for cmd in clips:
                self.assertEqual(cmd[cmd.index('-frames:v')+1],str(FPS*5))
                self.assertIn('-an',cmd)
                self.assertIn('zoompan=',cmd[cmd.index('-filter_complex')+1])
            self.assertNotIn('fade=',clips[0][clips[0].index('-filter_complex')+1])
            self.assertIn('fade=',clips[1][clips[1].index('-filter_complex')+1])
            self.assertEqual(len(listing.read_text().splitlines()),3)
            self.assertNotEqual(scene_filter(0,320,180),scene_filter(1,320,180))

    def test_static_or_changed_inputs_invalidate_old_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'song.json').write_text(json.dumps({'scenes':[{'index':0}]}))
            for name in ('song.wav','thumbnail-source.png','scene-000-source.png','video.mp4'):
                (root/name).write_bytes(b'fixture')
            self.assertFalse(render_is_current(root))
            (root/'render-state.json').write_text(json.dumps(render_identity(root)))
            self.assertTrue(render_is_current(root))
            (root/'scene-000-source.png').write_bytes(b'new illustration')
            self.assertFalse(render_is_current(root))
