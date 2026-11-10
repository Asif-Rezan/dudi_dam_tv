import json
import math
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
from scene_actions import plan_scene,actor_profile,state_at,foot_swing,face_motion,camera_viewport
from motion_video import transition_clip,run_ffmpeg,FPS


class AnimationPolishTests(unittest.TestCase):
    def test_scene_phase_and_pose_switch_follow_absolute_music_grid(self):
        for index in range(12):
            plan=plan_scene('clap and dance at 130 BPM',index)
            profile=actor_profile(plan,0,3)
            next_plan=plan_scene('clap and dance at 130 BPM',index+1)
            end=2*math.pi*5/plan['beat_seconds']+profile['phase']
            start=actor_profile(next_plan,0,3)['phase']
            self.assertAlmostEqual(math.sin(end),math.sin(start),places=10)
            grid=(index*5+plan['switch_at'])/plan['beat_seconds']
            self.assertAlmostEqual(grid,round(grid),places=10)
            self.assertEqual({actor_profile(plan,i,3)['phase'] for i in range(3)},{profile['phase']})

    def test_planted_steps_do_not_lift_whole_actor_and_one_foot_stays_down(self):
        plan=plan_scene('clap dance 130 BPM',8)
        for t in np.linspace(0,4.96,100):
            self.assertEqual(state_at(plan,float(t))['hop'],0)
            left=foot_swing(t,plan['beat_seconds'],side=-1)
            right=foot_swing(t,plan['beat_seconds'],side=1)
            self.assertLess(min(left,right),1e-20)

    def test_conservative_blink_changes_only_verified_eye_boxes(self):
        image=Image.new('RGBA',(100,160),(240,190,150,255))
        draw=ImageDraw.Draw(image);draw.rectangle((25,40,34,49),fill='black');draw.rectangle((60,40,69,49),fill='black')
        rig={'source':'conservative-eye-pair','eyes':[[.25,.25,.35,.3125],[.6,.25,.7,.3125]]}
        result=np.asarray(face_motion(image,rig,{'blink':1.}))
        before=np.asarray(image);changed=(result!=before).any(axis=2)
        self.assertTrue(changed.any())
        allowed=np.zeros((160,100),dtype=bool);allowed[40:50,25:35]=True;allowed[40:50,60:70]=True
        self.assertFalse(changed[~allowed].any())
        np.testing.assert_array_equal(face_motion(image,None,{'blink':1.}),image)
        np.testing.assert_array_equal(face_motion(image,rig,{'blink':0.}),image)

    def test_camera_has_no_mid_scene_jump_and_retains_cast(self):
        for size,bounds in [((1920,1080),(450,200,1400,1000)),((1080,1920),(100,400,980,1800))]:
            plan=plan_scene('dance 130 BPM',0)
            boxes=[camera_viewport(size,bounds,plan,float(t)) for t in np.linspace(0,4.96,125)]
            self.assertLess(max(abs(a-b) for x,y in zip(boxes,boxes[1:]) for a,b in zip(x,y)),size[0]*.004)
            for x,y,r,b in boxes:
                self.assertTrue(x<=bounds[0] and y<=bounds[1] and r>=bounds[2] and b>=bounds[3])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg runtime required')
    def test_real_dissolve_keeps_five_seconds_and_cache_reuses_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old.mp4';new=root/'new.mp4';out=root/'blend.mp4'
            for target,color in [(old,'red'),(new,'blue')]:
                run_ffmpeg(['-f','lavfi','-i',f'color={color}:s=160x90:r=25:d=5','-an','-c:v','libx264','-pix_fmt','yuv420p',str(target)])
            transition_clip(old,new,out,160,90)
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(out)]))
            self.assertAlmostEqual(float(data['format']['duration']),5,places=2)
            self.assertEqual(int(data['streams'][0]['nb_frames']),125)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-frames:v','6','-f','rawvideo','-pix_fmt','rgb24','-'])
            frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,90,160,3)
            self.assertGreater(frames[0,:,:,0].mean(),200)
            self.assertGreater(frames[-1,:,:,2].mean(),200)
            self.assertGreater(frames[2,:,:,0].mean(),20)
            self.assertGreater(frames[2,:,:,2].mean(),20)
            with patch('motion_video.run_ffmpeg',side_effect=AssertionError('unchanged transition reencoded')):
                transition_clip(old,new,out,160,90)
