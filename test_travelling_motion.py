import math
import unittest
import numpy as np
from PIL import Image
from scene_actions import plan_scene, travel_offset, travel_feet, compose_scene, stage_scene


class TravellingMotionTests(unittest.TestCase):
    def test_walk_run_and_chase_prompts_enable_real_travel(self):
        for cue,kind in [('walk towards friend to greet','walk'),('run to follow friend','run'),('chase friend','run'),('walk to fetch ball','walk'),('hop towards friend','hop')]:
            self.assertEqual(plan_scene(cue)['locomotion'],kind)
        self.assertIsNone(plan_scene('sleep under moon')['locomotion'])

    def test_path_is_smooth_visible_and_never_exits_frame(self):
        for size,bounds in [((640,360),(200,80,430,320)),((360,640),(80,180,260,570))]:
            plan=plan_scene('run to follow friend 130 BPM')
            shifts=[travel_offset(size,bounds,plan,float(t)) for t in np.linspace(0,5,126)]
            self.assertEqual(shifts[0],0)
            self.assertGreater(abs(shifts[-1]),size[0]*.1)
            for dx in shifts:
                self.assertGreaterEqual(bounds[0]+dx,size[0]*.025-.01)
                self.assertLessEqual(bounds[2]+dx,size[0]*.975+.01)
            self.assertLess(max(abs(a-b) for a,b in zip(shifts,shifts[1:])),size[0]*.006)
        self.assertEqual(travel_offset((100,100),(0,0,100,100),plan,3),0)

    def test_fixed_camera_proves_actors_move_relative_to_ground_not_just_camera(self):
        bg=Image.new('RGBA',(640,360),'white')
        parts=[(Image.new('RGBA',(60,120),'red'),(210,190,270,310),None),
               (Image.new('RGBA',(55,110),'blue'),(370,200,425,310),None)]
        plan=plan_scene('walk towards waiting friend to share a flower at 130 BPM')
        before=np.asarray(compose_scene(bg,parts,plan,0,camera=False,environment=False))
        after=np.asarray(compose_scene(bg,parts,plan,4.8,camera=False,environment=False))
        centers=[]
        for ordinal,color in enumerate(([255,0,0],[0,0,255])):
            a=np.where((before[:,:,:3]==color).all(axis=2))[1]
            b=np.where((after[:,:,:3]==color).all(axis=2))[1]
            if ordinal==0: self.assertGreater(abs(b.mean()-a.mean()),70)
            else: self.assertLess(abs(b.mean()-a.mean()),1)
            centers.append(b.mean())
        self.assertLess(centers[0],centers[1])

    def test_stance_compensation_holds_foot_in_world_coordinates(self):
        size=(640,360);bounds=(200,80,430,320)
        parts=[(None,(200,80,300,320),None),(None,(500,80,560,320),None)]
        plan=stage_scene(plan_scene('walk towards friend 120 BPM'),parts,size)[0][0]
        beat=plan['beat_seconds']
        # Same left-foot stance, while the root continues moving.
        times=[beat*(2+u) for u in (.6,.7,.8,.9)]
        anchors=[travel_offset(size,bounds,plan,t)-travel_feet(size,bounds,plan,t)[0] for t in times]
        self.assertLess(max(anchors)-min(anchors),1e-9)

    def test_camera_preserves_both_actors_during_locomotion(self):
        bg=Image.new('RGBA',(320,180),'white')
        parts=[(Image.new('RGBA',(30,65),'red'),(100,90,130,155),None),
               (Image.new('RGBA',(30,60),'blue'),(210,90,240,150),None)]
        for t in np.linspace(0,4.96,20):
            pixels=np.asarray(compose_scene(bg,parts,plan_scene('run to follow friend 130 BPM'),float(t)))
            for color in ([255,0,0],[0,0,255]):
                self.assertGreater(((pixels[:,:,:3]==color).all(axis=2)).sum(),500)


    def test_unmotivated_walk_or_plain_dance_does_not_move_the_group(self):
        for text in ('clap and dance together','walk across meadow','hop dance','both friends wait'):
            plan=plan_scene(text)
            self.assertIsNone(plan['intent'])
            self.assertEqual(travel_offset((640,360),(200,80,430,320),plan,4),0)

    def test_friend_route_approaches_target_stops_and_preserves_waiting_friend(self):
        parts=[(None,(80,70,140,230),None),(None,(350,80,420,240),None)]
        plan=plan_scene('left friend walks toward waiting friend to share a flower')
        routes=stage_scene(plan,parts,(640,360))
        mover,receiver=routes[0][0],routes[1][0]
        self.assertEqual(mover['target_actor'],1)
        self.assertEqual(receiver['role'],'waiting_friend')
        self.assertEqual(travel_offset((640,360),parts[1][1],receiver,4),0)
        for t in np.linspace(0,5,50):
            dx=travel_offset((640,360),parts[0][1],mover,t)
            self.assertLessEqual(parts[0][1][2]+dx,parts[1][1][0]-16)
        self.assertEqual(travel_offset((640,360),parts[0][1],mover,3.5),travel_offset((640,360),parts[0][1],mover,5))
        self.assertGreater(travel_offset((640,360),parts[0][1],mover,3.5),0)
        # A single actor cannot approach an invented invisible friend.
        alone=stage_scene(plan,parts[:1],(640,360))[0][0]
        self.assertEqual(alone['route_dx'],0)

    def test_followers_start_after_leader_and_keep_spatial_order(self):
        parts=[(None,(80,70,130,230),None),(None,(220,80,270,240),None),(None,(350,90,400,250),None)]
        routes=stage_scene(plan_scene('friends follow leader'),parts,(640,360))
        leader=next(p for p,_ in routes if p['role']=='leader')
        for local,_ in routes:
            if local['role']=='follower': self.assertGreater(local['route_start'],leader['route_start'])
        for t in np.linspace(0,5,50):
            boxes=[(part[1][0]+travel_offset((640,360),part[1],local,t),part[1][2]+travel_offset((640,360),part[1],local,t)) for part,(local,_) in zip(parts,routes)]
            self.assertTrue(all(a[1]<b[0] for a,b in zip(boxes,boxes[1:])))

    def test_ball_route_ends_near_the_explicit_rendered_target(self):
        parts=[(None,(220,70,300,230),None)]
        local,_=stage_scene(plan_scene('walk to fetch ball'),parts,(640,360))[0]
        dx=travel_offset((640,360),parts[0][1],local,4)
        x,y=local['prop_target']
        nearest=parts[0][1][2]+dx if dx>0 else parts[0][1][0]+dx
        self.assertGreater(abs(dx),20)
        self.assertLess(abs(nearest-x),30)


    def test_unrelated_or_sleeping_greetings_do_not_invent_a_friend_route(self):
        for text in ('Hello sunshine in the sky','follow a little butterfly','friends share a peaceful sleep'):
            self.assertIsNone(plan_scene(text)['intent'])
