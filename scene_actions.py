"""Small timed stories for CPU puppet scenes; no external inference calls.

Face coordinates are normalized to the cropped actor, never the whole scene.
Uncertain/multiple faces retain their original artwork rather than guessed eyes.
"""
import hashlib
import math
import re
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

VERSION = 'scene-stories-v13-purposeful-interactions'
OPENING_SCENES = 3  # first 15 seconds
BODY_VARIANTS = ('wave', 'waist', 'step', 'hop', 'tummy', 'jelly', 'clap', 'penguin')
SWITCH_AT = 2.5
DANCE_VARIANTS = ('wave', 'waist', 'step', 'sway', 'hop', 'tummy', 'jelly', 'clap', 'penguin', 'balloons', 'fireflies', 'ripple_hop')


def smooth(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


def movement_intent(prompt):
    """Only choose spatial goals grounded in literal scene actions."""
    text=prompt.lower()
    words=set(re.findall(r'[a-z]+',text))
    if re.search(r'\b(in place|stay still|stand still|both friends wait)\b',text):
        return None,None
    friend_goal=bool(words & {'friend','friends','companion','companions','buddy','buddies','leader'} or {'left','right'}<=words or 'each other' in text)
    if words & {'sleep','sleeping','rest','resting'} and not words & {'walk','walks','walking','run','runs','running','approach','approaches','toward','towards'}:
        return None,None
    if friend_goal and words & {'follow','follows','following','lead','leads','leading','chase','chases','chasing'}:
        return 'follow_friend','follow the leading friend'
    if words & {'ball'} and words & {'fetch','fetches','fetching','collect','collects','kick','roll','rolling','catch'}:
        return 'approach_ball','reach the visible ball'
    reasons=[({'share','shares','sharing','give','gives','giving','offer','offers','offering','bring','brings'},'share with the waiting friend'),
             ({'help','helps','helping'},'help the waiting friend'),
             ({'greet','greets','greeting','hello','meet','meets','meeting','join','joins','joining'},'greet or join the waiting friend')]
    for cues,reason in reasons:
        if friend_goal and words & cues:
            return 'approach_friend',reason
    if words & {'friend','friends','companion','companions'} and words & {'toward','towards','approach','approaches','approaching'}:
        return 'approach_friend','reach the waiting friend'
    return None,None


def plan_scene(prompt, index=0):
    words = set(re.findall(r'[a-z]+', prompt.lower()))
    intent,purpose=movement_intent(prompt)
    if words & {'run','runs','running','walk','walks','walking','chase','chasing','dance','dances','dancing','clap','claps','clapping','bounce','bounces','bouncing','wiggle','wiggling','twirl','twirling','stomp','stomping','tummy','belly','jelly','penguin','peekaboo','leader','bob','flop','spin','spinning','rotate','rotation','balloons','fireflies','ripple'}:
        kind, prop, action = 'dance', None, 'dance'
    elif words & {'sleep', 'sleepy', 'sleeping', 'bed', 'night', 'moon'}:
        kind, prop, action = 'rest', 'star', 'settle'
    elif words & {'rain', 'rainy', 'water', 'splash', 'puddle'}:
        kind, prop, action = 'rain', 'droplet', 'sway'
    elif words & {'ball', 'roll', 'rolling', 'kick', 'catch'}:
        kind, prop, action = 'play', 'ball', 'approach'
    elif words & {'rabbit', 'bunny', 'hare', 'hop', 'hopping', 'jump', 'jumping'}:
        kind, prop, action = 'discover', 'butterfly', 'two_hops'
    else:
        kind, prop, action = 'discover', 'butterfly', 'approach'
    seed=int.from_bytes(hashlib.sha256(f'{index}:{prompt}'.encode()).digest()[:8],'big')
    variant=DANCE_VARIANTS[seed % len(DANCE_VARIANTS)]
    # Literal lyric instructions take priority over deterministic variety.
    literal_move=False
    for cues, selected in [(('twirl','twirling','spin','spinning','rotate','rotation'),'sway'),
                           (('tummy','belly','wiggle','wiggling'),'tummy'),
                           (('jelly','bounce','bounces','bouncing'),'jelly'),
                           (('clap','claps','clapping'),'clap'),
                           (('penguin',),'penguin'), (('balloons','bob','flop'),'balloons'),
                           (('fireflies','peekaboo'),'fireflies'), (('ripple','leader'),'ripple_hop'), (('hop','hopping','jump','jumping'),'hop'),
                           (('step','steps','stepping'),'step'), (('wave','waves','waving'),'wave')]:
        if words.intersection(cues):
            variant=selected
            literal_move=True
            break
    tempo=re.search(r'\b(\d{2,3})\s*bpm\b',prompt,re.I)
    bpm=int(tempo.group(1)) if tempo else 100
    bpm=bpm if 30<=bpm<=300 else 100
    # A second move halfway through gives every dance scene two distinct poses.
    choices=[v for v in BODY_VARIANTS if v!=variant and (v!='hop' or variant in ('hop','jelly','ripple_hop'))]
    second=choices[(seed>>8) % len(choices)]
    beat_seconds=60/bpm
    # Retain the music's phase across five-second scene boundaries. Chorus
    # choreography repeats in four-scene phrases instead of random poses.
    if kind=='dance' and not literal_move:
        variant=('step','wave','clap','sway')[index % 4]
        second=('wave','clap','step','waist')[index % 4]
    switch_at=beat_seconds*round((index*5+SWITCH_AT)/beat_seconds)-index*5
    locomotion=('run' if words & {'run','runs','running','chase','chasing'} else
                'walk' if words & {'walk','walks','walking'} else
                'hop' if variant in ('hop','jelly','ripple_hop') else 'side_step') if kind=='dance' else None
    if intent:
        locomotion=locomotion or ('hop' if words & {'hop','hopping','jump','jumping'} else 'walk')
        if intent in ('approach_friend','follow_friend'):
            prop=None
    else:
        locomotion=None  # No unexplained drift for ordinary dance or standing.
    return dict(version=VERSION, kind=kind, prop=prop, action=action, dance_variant=variant,beat_seconds=60/bpm,
                intent=intent,purpose=purpose,
                locomotion=locomotion,
                beat_origin=index*5, switch_at=switch_at,
                second_variant=second, opening=index<OPENING_SCENES,
                direction=1 if index % 2 == 0 else -1,
                beats=[dict(at=0., action='original_expression'), dict(at=.65, action='prop_enters'),
                       dict(at=1.35, action='look'), dict(at=2.1, action=action),
                       dict(at=4.1, action='close_up_reaction')])


def state_at(plan, t):
    progress = smooth((t - 2.1) / 1.7)
    hop = landing = 0.
    if plan['action'] == 'two_hops':
        for start in (2.1, 3.0):
            u = (t - start) / .65
            if 0 < u < 1:
                hop = math.sin(math.pi * u)
            landing += math.exp(-((t - start - .68) / .09)**2)
    if plan['action']=='dance':
        ramp=smooth((t-.3)/.4)*smooth((5-t)/.4)
        beat=2*math.pi*(t+plan.get('beat_origin',0))/plan.get('beat_seconds',.6)
        mix=smooth((t-plan.get('switch_at',SWITCH_AT)+.2)/.4)
        hopping=('hop','jelly','ripple_hop')
        weight=(1-mix)*(plan.get('dance_variant') in hopping)+mix*(plan.get('second_variant') in hopping)
        hop=max(0.,math.sin(beat))*ramp*weight
        landing=max(0.,-math.sin(beat))**6*ramp*weight
    blink = blink_at(t)
    return dict(progress=progress, hop=hop, landing=landing, blink=blink,
                look=smooth((t - 1.35) / .5), reaction=smooth((t - 4.1) / .65),
                direction=plan['direction'])


def detect_face(actor):
    """Conservative dark-eye pair proposal, restricted to one opaque silhouette.

This is deliberately optional: full scenes with kids AND animals can have
multiple faces. Never apply a guessed blink to a whole multi-character group.
"""
    from scipy import ndimage
    pixels = np.asarray(actor)
    h, w = pixels.shape[:2]
    dark = (pixels[:, :, :3].max(axis=2) < 85) & (pixels[:, :, 3] > 240)
    dark[:int(h*.15)] = False
    dark[int(h*.7):] = False
    labels, count = ndimage.label(dark)
    candidates = []
    for label, region in enumerate(ndimage.find_objects(labels), 1):
        if region is None:
            continue
        ys, xs = region
        bw, bh = xs.stop-xs.start, ys.stop-ys.start
        area = int((labels[region] == label).sum())
        if w*.025 < bw < w*.19 and h*.025 < bh < h*.17 and area > w*h*.0008:
            candidates.append((xs.start, ys.start, xs.stop, ys.stop))
    pairs = []
    for i, a in enumerate(candidates):
        for b in candidates[i+1:]:
            ac, bc = ((a[0]+a[2])/2,(a[1]+a[3])/2), ((b[0]+b[2])/2,(b[1]+b[3])/2)
            gap = abs(ac[0]-bc[0])
            ratio = (a[3]-a[1])/(b[3]-b[1])
            if .12*w < gap < .42*w and abs(ac[1]-bc[1]) < .045*h and .6 < ratio < 1.7:
                pairs.append((a,b))
    if len(pairs) != 1:
        return None
    return dict(eyes=[[a[0]/w,a[1]/h,a[2]/w,a[3]/h] for a in pairs[0]], source='conservative-eye-pair')


def blink_at(t):
    return smooth(max(0.,1-abs((t % 4.6)-1.9)/.16))


def face_motion(actor, rig, state):
    """A brief eyelid closure only on one verified pair; never redraw a mouth."""
    result=actor.copy()
    amount=state.get('blink',0.)
    if not rig or rig.get('source')!='conservative-eye-pair' or amount<=0:
        return result
    pixels=np.asarray(actor)
    w,h=actor.size
    for box in rig['eyes']:
        x,y,r,b=(round(v*n) for v,n in zip(box,(w,h,w,h)))
        if not (2<=x<r<w-2 and 2<=y<b<h-2):
            continue
        # Skip textured/transparent skin instead of painting guessed eyelids.
        ring=pixels[max(0,y-2):y,x:r]
        if ring.size==0 or ring[:,:,3].min()<240 or np.ptp(ring[:,:,:3].astype(float),axis=(0,1)).max()>45:
            continue
        color=tuple(np.median(ring.reshape(-1,4),axis=0).astype('uint8'))
        patch=actor.crop((x,y,r,b))
        ImageDraw.Draw(result).rectangle((x,y,r-1,b-1),fill=color)
        height=max(1,round((b-y)*(1-.92*amount)))
        patch=patch.resize((r-x,height),Image.Resampling.LANCZOS)
        result.alpha_composite(patch,(x,y+(b-y-height)//2))
    return result


def draw_prop(canvas, plan, t, anchor, travel):
    if t < .65 or plan.get('prop') is None:
        return
    w,h = canvas.size
    direction=plan['direction']
    enter=smooth((t-.65)/1.0)
    destination=anchor[0]+direction*max(abs(travel)*1.25,w*.12)
    x=(w+30 if direction>0 else -30)*(1-enter)+destination*enter
    y=anchor[1] + h*.025*math.sin(t*4)
    size=max(5,round(min(w,h)*.025))
    d=ImageDraw.Draw(canvas)
    if plan.get('prop_target') and plan['prop']=='ball':
        x,y=plan['prop_target']
        d.ellipse((x-size,y-size,x+size,y+size),fill=(255,181,78,255),outline=(232,120,106,255),width=2)
        return
    if plan['prop']=='butterfly':
        flap=.22+.78*abs(math.sin(t*12))
        wing=max(2,round(size*flap))
        for side in (-1,1):
            d.ellipse((x+side*wing-wing,y-size,x+side*wing+wing,y+size*.4),fill=(247,172,76,235))
            d.ellipse((x+side*wing*.8-wing*.7,y,x+side*wing*.8+wing*.7,y+size),fill=(247,121,162,235))
        d.line((x,y-size*.6,x,y+size*.6),fill=(94,64,87,255),width=max(1,size//5))
    elif plan['prop']=='ball':
        y=anchor[1]+h*.22-abs(math.sin(t*4))*size
        d.ellipse((x-size,y-size,x+size,y+size),fill=(255,181,78,255),outline=(232,120,106,255),width=2)
    elif plan['prop']=='star':
        points=[(x+math.cos(i*math.pi/5-math.pi/2)*size*(1 if i%2==0 else .45),
                 y+math.sin(i*math.pi/5-math.pi/2)*size*(1 if i%2==0 else .45)) for i in range(10)]
        d.polygon(points,fill=(255,225,145,220))
    else:
        for i in range(5):
            px=(x+i*w*.09)%w
            py=(t*h*.17+i*h*.14)%(h*.7)
            d.line((px,py,px-2,py+size),fill=(151,207,245,175),width=max(1,size//5))


def background_motion(background, t):
    """Subtle sky parallax and foliage sway; floor and frame edges stay fixed.

    This uses the cleaned background only, so character faces never bend with
    the scenery. It needs no extra images or per-frame model inference.
    """
    w,h=background.size
    mesh=[]
    def point(x,y):
        u,v=x/w,y/h
        edge=math.sin(math.pi*u)
        sky=max(0,1-v/.60)
        foliage=math.exp(-((v-.58)/.22)**4)
        grass=math.exp(-((v-.88)/.055)**4)
        dx=edge*w*(.004*math.sin(t*.75)*sky+
            .0028*math.sin(t*1.8+u*5)*foliage+
            .0018*math.sin(t*2.6+u*9)*grass)
        dy=h*.0015*math.sin(math.pi*v)*math.sin(t*1.3+u*4)*foliage
        return max(0,min(w,x+dx)),max(0,min(h,y+dy))
    for y in range(0,h,48):
        for x in range(0,w,48):
            r,b=min(w,x+48),min(h,y+48)
            mesh.append(((x,y,r,b),tuple(c for pt in [point(x,y),point(x,b),point(r,b),point(r,y)] for c in pt)))
    return background.transform(background.size,Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)


def camera_viewport(size, bounds, plan, t):
    """A continuous push-in and gentle pan, bounded to retain the whole cast."""
    w,h=size
    left,top,right,bottom=bounds
    mx,my=w*.025,h*.025
    # Limit zoom for edge-to-edge/tall/portrait compositions.
    progress=smooth(t/5)
    desired=1+(.10 if plan.get('opening') else .065)*progress
    sway=w*.008*plan.get('direction',1)*math.sin(math.pi*progress)**2
    zoom=max(1,min(desired,w/max(1,right-left+2*mx),h/max(1,bottom-top+2*my)))
    cw,ch=w/zoom,h/zoom
    wanted_x=(left+right)/2-cw/2+sway
    wanted_y=(top+bottom)/2-ch/2
    low_x=max(0,right+mx-cw);high_x=min(w-cw,left-mx)
    low_y=max(0,bottom+my-ch);high_y=min(h-ch,top-my)
    x=max(low_x,min(high_x,wanted_x)) if low_x<=high_x else (w-cw)/2
    y=max(low_y,min(high_y,wanted_y)) if low_y<=high_y else (h-ch)/2
    return (x,y,x+cw,y+ch)


def apply_camera(canvas, bounds, plan, t):
    return canvas.resize(canvas.size,Image.Resampling.BICUBIC,
        box=camera_viewport(canvas.size,bounds,plan,t)).convert('RGB')


def actor_profile(plan, ordinal, count):
    if plan['action']=='dance':
        variant=plan.get('dance_variant','hop')
        follow=variant=='ripple_hop'
        return dict(movement='dance',variant=variant,
                    delay=ordinal*plan.get('beat_seconds',.6)/2 if follow else 0.,
                    phase=2*math.pi*plan.get('beat_origin',0)/plan.get('beat_seconds',.6),
                    energy=1-.08*(ordinal%3), blink_offset=ordinal*.37)
    if count==1:
        return dict(movement=plan['action'],delay=0.,phase=0.)
    if plan['action']=='settle':
        movement='settle'
    else:
        movement=(('sway','two_hops','nod') if plan['action']=='two_hops' else ('sway','nod','sway'))[ordinal%3]
    return dict(movement=movement,delay=ordinal*.22,phase=ordinal*1.7)


GAINS = {
    'wave':(1.4,.15,.3),'waist':(.25,.15,1.5),
    'step':(.3,1.4,.4),'sway':(.25,.15,.7),
    'hop':(.7,.7,.6), 'tummy':(.45,.25,2.1), 'jelly':(.7,.6,1.),
    'clap':(1.2,1.,.45), 'penguin':(.8,1.3,.6),
}


def foot_swing(t, beat_seconds=.6, phase=0., side=-1):
    """Alternating swing legs leave the other foot planted on each half beat."""
    return max(0.,math.sin(2*math.pi*t/beat_seconds+phase+(math.pi if side>0 else 0)))**2


def dance_body_motion(subject, t, phase=0., variant='hop', beat_seconds=.6, second=None, energy=1., switch_at=SWITCH_AT, protect=.65, foot_offsets=None):
    """Blend lower-body poses continuously while preserving original head pixels."""
    ramp=smooth(t/.4)*smooth((5-t)/.35)
    if variant in ('balloons','fireflies','ripple_hop') or ramp==0:
        return subject.copy()
    if foot_offsets is not None and max(abs(v) for v in foot_offsets)>.1:
        padding=math.ceil(max(abs(v) for v in foot_offsets))+2
        subject=ImageOps.expand(subject,border=(padding,0,padding,0),fill=(0,0,0,0))
    w,h=subject.size
    mix=smooth((t-switch_at+.2)/.4) if second in GAINS else 0.
    beat=2*math.pi*t/beat_seconds+phase
    mesh=[]
    def offset(u,v,name):
        arm_gain,leg_gain,waist_gain=GAINS.get(name,(.7,.7,.6))
        side=math.tanh((u-.5)*6)
        arms=arm_gain*math.exp(-((v-.69)/.10)**4)*abs(side)**2
        waist=waist_gain*math.exp(-((v-.76)/.10)**4)
        dx=w*(.015*math.sin(beat)*waist+.012*math.sin(beat+side*.7)*arms)
        dy=h*.012*math.sin(beat+side*1.2)*arms
        if name=='tummy':
            belly=math.exp(-((u-.5)/.35)**4-((v-.72)/.12)**4)
            dx+=w*.018*math.sin(beat)*belly
        elif name=='clap':
            dx+=w*.045*side*arms*(.5-.5*math.cos(beat))
        foot=smooth((v-.82)/.16)
        swing=foot_swing(t,beat_seconds,phase,side)
        foot_x=w*.018*side*leg_gain*swing
        if foot_offsets is not None:
            # Inverse-mesh displacement compensates body travel during stance.
            # The planted foot stays in world space instead of skating along.
            foot_x=foot_offsets[1 if side>0 else 0]
        dx=dx*(1-foot)+foot_x*foot
        dy=dy*(1-foot)+h*.06*leg_gain*swing*foot
        gate=smooth((v-.65)/.08)
        return dx*gate,dy*gate
    def point(x,y):
        u,v=x/w,y/h
        first=offset(u,v,variant);last=offset(u,v,second or variant)
        # Root-travel compensation must not be attenuated with actor energy.
        dx=energy*ramp*((1-mix)*first[0]+mix*last[0])
        if foot_offsets is not None:
            foot=smooth((v-.82)/.16)*smooth((v-.65)/.08)
            correction=foot_offsets[1 if u>.5 else 0]*foot
            dx+=correction*(1-energy*ramp)
        return (x+dx,
                y+energy*ramp*((1-mix)*first[1]+mix*last[1]))
    for y in range(0,h,12):
        for x in range(0,w,12):
            r,b=min(w,x+12),min(h,y+12)
            mesh.append(((x,y,r,b),tuple(c for pt in [point(x,y),point(x,b),point(r,b),point(r,y)] for c in pt)))
    result=subject.transform(subject.size,Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)
    result.paste(subject.crop((0,0,w,round(h*protect))),(0,0))
    return result


def draw_bubbles(canvas, t):
    """Sparse slow background bubbles, composited behind the cast."""
    w,h=canvas.size
    overlay=Image.new('RGBA',canvas.size)
    draw=ImageDraw.Draw(overlay)
    for i in range(7):
        radius=max(3,round(min(w,h)*(.012+.003*(i%3))))
        x=w*((i+.5)/7+.015*math.sin(t*.9+i))
        y=h*(1.12-((t*.085+i*.157)%1.3))
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),
                     outline=(185,225,255,150),width=max(1,round(radius*.12)))
        draw.arc((x-radius*.6,y-radius*.6,x+radius*.6,y+radius*.6),
                 205,280,fill=(255,255,255,190),width=max(1,round(radius*.15)))
    return Image.alpha_composite(canvas.convert('RGBA'),overlay)


def draw_environment_effect(canvas, plan, t):
    canvas=draw_bubbles(canvas,t)
    variant=plan.get('dance_variant')
    if variant not in ('balloons','fireflies'):
        return canvas
    w,h=canvas.size
    layer=Image.new('RGBA',canvas.size)
    d=ImageDraw.Draw(layer)
    if variant=='balloons':
        for i,color in enumerate(((255,154,178,210),(156,204,255,210),(255,215,113,210))):
            x=w*(.12+i*.36)+w*.018*math.sin(t*1.2+i)
            y=h*(.95-((t*.12+i*.31)%1.25))
            r=min(w,h)*.055
            d.line((x,y+r,x+r*.15,y+r*3),fill=(210,218,230,190),width=1)
            d.ellipse((x-r*.75,y-r,x+r*.75,y+r),fill=color)
            d.arc((x-r*.5,y-r*.7,x+r*.35,y+r*.5),185,265,fill=(255,255,255,220),width=2)
    else:
        for i in range(12):
            x=w*(.06+(i*.173)% .88)+w*.025*math.sin(t*.8+i)
            y=h*(.15+(i*.227)%.68)+h*.025*math.cos(t+i)
            radius=min(w,h)*(.005+.004*(.5+.5*math.sin(t*2+i)))
            d.ellipse((x-radius*2,y-radius*2,x+radius*2,y+radius*2),fill=(255,226,120,45))
            d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(255,244,176,210))
    return Image.alpha_composite(canvas.convert('RGBA'),layer)


def travel_offset(size, bounds, plan, t):
    """One smooth on-ground path, constrained by the complete cast's free room."""
    if 'route_dx' in plan:
        return plan['route_dx']*smooth((t-plan.get('route_start',.7))/(plan.get('route_end',3.4)-plan.get('route_start',.7)))
    if not plan.get('locomotion') or plan.get('intent')!='follow_friend':
        return 0.
    w,h=size
    left,top,right,bottom=bounds
    margin=w*.025
    rooms=(max(0,left-margin),max(0,w-right-margin))
    direction=1 if rooms[1]>rooms[0] else -1
    room=rooms[1] if direction>0 else rooms[0]
    running=plan['locomotion']=='run'
    distance=min(room,w*(.32 if running else .25))
    return direction*distance*smooth((t-.2)/(3.3 if running else 4.2))


def stage_scene(plan, parts, size):
    """Assign geometry-based roles; do not guess names/species from cutouts."""
    w,h=size
    routes=[]
    for i,part in enumerate(parts):
        profile=actor_profile(plan,i,len(parts))
        local=dict(plan,route_dx=0.,role='participant',target_actor=None)
        if plan.get('intent'):
            profile=dict(actor_profile(dict(plan,action='dance'),i,len(parts)),movement='wait')
            local['role']='waiting_friend'
        routes.append((local,profile))
    intent=plan.get('intent')
    if intent=='approach_friend' and len(parts)>=2:
        # Nearest spatial neighbor is reliable; semantic identity is not inferred.
        mover,target=parts[0][1],parts[1][1]
        gap=max(0,target[0]-mover[2]-max(8,w*.025))
        local,profile=routes[0]
        local.update(route_dx=gap,role='approaching_friend',target_actor=1,
                     dance_variant='step',second_variant='wave',switch_at=3.4)
        profile.update(movement='dance',variant='step')
    elif intent=='follow_friend' and parts:
        bounds=(min(x[1][0] for x in parts),min(x[1][1] for x in parts),
                max(x[1][2] for x in parts),max(x[1][3] for x in parts))
        base=dict(plan);base.pop('route_dx',None)
        distance=travel_offset(size,bounds,base,5.)
        order=list(range(len(parts))) if distance<0 else list(reversed(range(len(parts))))
        for rank,i in enumerate(order):
            local,profile=routes[i]
            lag=rank*plan.get('beat_seconds',.6)*.5
            local.update(route_dx=distance,route_start=.5+lag,route_end=3.3+lag,
                         role='leader' if rank==0 else 'follower',target_actor=None if rank==0 else order[rank-1])
            profile.update(movement='dance',variant='step')
    elif intent=='approach_ball' and parts:
        box=parts[0][1]
        left=max(w*.025,box[0]-w*.25)
        right=min(w*.975,parts[1][1][0]-w*.03 if len(parts)>1 else w*.975)
        side=1 if right-box[2]>box[0]-left else -1
        room=max(0,right-box[2] if side>0 else box[0]-left)
        distance=max(0,room-w*.055)*.75
        target_x=(box[2] if side>0 else box[0])+side*(distance+w*.04)
        for local,_ in routes:
            local['prop_target']=(target_x,box[3]-h*.025)
        local,profile=routes[0]
        local.update(route_dx=side*distance,role='ball_seeker',prop='ball',dance_variant='step',
                     second_variant='wave',switch_at=3.4)
        profile.update(movement='dance',variant='step')
    return routes


def travel_feet(size,bounds,plan,t,delay=0.):
    """World-space stance holds, smoothly advancing the swing foot each stride."""
    beat=plan.get('beat_seconds',.6)
    current=travel_offset(size,bounds,plan,t)
    offsets=[]
    for side in (0,.5):
        fraction=((t-delay+plan.get('beat_origin',0))/beat+side)%1
        if fraction<.5:
            before=travel_offset(size,bounds,plan,t-(fraction+.5)*beat)
            after=travel_offset(size,bounds,plan,t+(.5-fraction)*beat)
            anchor=before+(after-before)*smooth(fraction*2)
        else:
            anchor=travel_offset(size,bounds,plan,t-(fraction-.5)*beat)
        offsets.append(current-anchor)
    return tuple(offsets)


def compose_frame(bg, subject, bbox, plan, t, rig=None, camera=True, prop=True, profile=None):
    profile=profile or actor_profile(plan,0,1)
    local_t=max(0,t-profile['delay'])
    local_plan=dict(plan,action=profile['movement'],dance_variant=profile.get('variant',plan.get('dance_variant','hop')))
    state=state_at(local_plan,local_t)
    state['blink']=blink_at(local_t+profile.get('blink_offset',0))
    w,h=bg.size
    room_right=max(0,w-bbox[2]-4)
    room_left=max(0,bbox[0]-4)
    direction=1 if room_right>=room_left else -1
    state['direction']=direction
    plan=dict(plan,direction=direction)
    movement=profile['movement']
    # Group members stay within their own space instead of sliding together.
    travel=0.  # Spatial movement comes from a grounded interaction route only.
    route_bounds=profile.get('route_bounds',bbox)
    if movement=='dance':
        travel=travel_offset(bg.size,route_bounds,plan,t)
    lift=state['hop']*min(h*.055,max(0,bbox[1]*.35))
    if movement=='dance' and plan.get('locomotion')=='run':
        lift+=min(h*.018,bbox[1]*.15)*math.sin(2*math.pi*(local_t+plan.get('beat_origin',0))/plan['beat_seconds'])**2*smooth(local_t/.4)*smooth((5-t)/.4)
    angle=0.
    if movement=='sway':
        angle=2.2*math.sin(local_t*2.4+profile['phase'])*smooth(local_t/.45)
    # Keep original sprite proportions: never squeeze, stretch or rotate dancers.
    actor=face_motion(subject,rig,state)
    if movement=='dance':
        body_variant='step' if local_plan['dance_variant'] in ('balloons','fireflies') and plan.get('locomotion') else local_plan['dance_variant']
        actor=dance_body_motion(actor,local_t,profile['phase'],body_variant,local_plan.get('beat_seconds',.6),
                                second=plan.get('second_variant'),energy=profile.get('energy',1.),
                                switch_at=plan.get('switch_at',SWITCH_AT),
                                protect=max(.65,min(.9,max((b[3] for b in rig['eyes']),default=0)+.1)) if rig else .65,
                                foot_offsets=travel_feet(bg.size,route_bounds,plan,t,profile['delay']) if plan.get('locomotion') else None)
    if angle:
        actor=actor.rotate(angle,Image.Resampling.BICUBIC,expand=True)
    actor.thumbnail((w,h),Image.Resampling.BICUBIC)
    cx=(bbox[0]+bbox[2])/2+travel*(1 if movement=='dance' else state['progress'])
    x=max(0,min(w-actor.width,round(cx-actor.width/2)))
    y=max(0,min(h-actor.height,round(bbox[3]-actor.height-lift)))
    canvas=background_motion(bg,t).convert('RGBA') if camera else bg.copy().convert('RGBA')
    if camera and plan['kind']=='dance':
        canvas=draw_environment_effect(canvas,plan,t)
    shadow=Image.new('RGBA',bg.size)
    d=ImageDraw.Draw(shadow)
    radius=subject.width*.28*(1-.25*state['hop'])
    d.ellipse((cx-radius,bbox[3]-h*.012,cx+radius,bbox[3]+h*.012),fill=(45,47,60,round(45-15*state['hop'])))
    canvas=Image.alpha_composite(canvas,shadow.filter(ImageFilter.GaussianBlur(max(1,h*.01))))
    canvas.alpha_composite(actor,(x,y))
    face_y=y+subject.height*(sum((b[1]+b[3])/2 for b in rig['eyes'])/len(rig['eyes']) if rig else .4)
    if prop:
        draw_prop(canvas,plan,t,(cx,face_y),travel)
    if not camera:
        return canvas
    bounds=(max(0,x-subject.width*.04),max(0,y-h*.08),
            min(w,x+actor.width+subject.width*.04),min(h,y+actor.height))
    return apply_camera(canvas,bounds,plan,t)


def actor_parts(foreground,split_touching=False):
    """Separate disjoint substantial silhouettes so friends react independently."""
    from scipy import ndimage
    alpha=np.asarray(foreground)[:,:,3]
    labels,count=ndimage.label(alpha>64)
    split=False
    if split_touching and count==1:
        # Remove only thin contact bridges to propose separate body cores;
        # all original pixels are then assigned to the nearest core below.
        cores=ndimage.binary_opening(alpha>64,iterations=max(1,round(min(alpha.shape)*.009)))
        candidates,n=ndimage.label(cores)
        sizes=np.bincount(candidates.ravel());sizes[0]=0
        keep=np.flatnonzero(sizes>=max(sizes.max()*.06,20))
        if 2<=len(keep)<=4:
            labels=np.where(np.isin(candidates,keep),candidates,0)
            count=len(keep)
            split=True
    areas=np.bincount(labels.ravel());areas[0]=0
    if not count:
        return []
    parts=[]
    _,nearest=ndimage.distance_transform_edt(labels==0,return_indices=True)
    owners=labels[tuple(nearest)]
    for number in np.flatnonzero(areas>=max(areas.max()*.03,20)):
        mask=(owners==number) if split else ndimage.binary_dilation(labels==number,iterations=2) & (owners==number)
        item=foreground.copy()
        item.putalpha(Image.fromarray(np.where(mask,alpha,0).astype('uint8')))
        bbox=item.getbbox()
        if bbox:
            subject=item.crop(bbox)
            parts.append((subject,bbox,detect_face(subject)))
    return sorted(parts,key=lambda part:part[1][0])


def compose_scene(bg, parts, plan, t, camera=True, environment=True):
    if not parts:
        canvas=background_motion(bg,t) if environment else bg.copy()
        return apply_camera(canvas,(0,0,*bg.size),plan,t) if camera else canvas.convert('RGB')
    routes=stage_scene(plan,parts,bg.size)
    if len(parts)==1 and camera and environment:
        subject,bbox,rig=parts[0]
        local,profile=routes[0]
        return compose_frame(bg,subject,bbox,local,t,rig,profile=profile)
    canvas=background_motion(bg,t) if environment else bg.copy()
    if environment and plan['kind']=='dance':
        canvas=draw_environment_effect(canvas,plan,t)
    w,h=bg.size
    left=min(p[1][0]-p[0].width*.04 for p in parts)
    top=min(p[1][1] for p in parts)-h*.08
    right=max(p[1][2]+p[0].width*.04 for p in parts)
    bottom=max(p[1][3] for p in parts)
    # Painter's order follows the feet, independent of animation timing/order.
    for i,(subject,bbox,rig) in sorted(enumerate(parts),key=lambda item:item[1][1][3]):
        local,profile=routes[i]
        canvas=compose_frame(canvas,subject,bbox,local,t,rig,camera=False,prop=False,
            profile=dict(profile,route_bounds=(left,top,right,bottom)))
    prop_plan=routes[0][0]
    draw_prop(canvas,prop_plan,t,((left+right)/2,top+(bottom-top)*.35),w*.10)
    shifts=[travel_offset(bg.size,(left,top,right,bottom),local,t) for local,_ in routes]
    moving_left=min(p[1][0]+dx-p[0].width*.04 for p,dx in zip(parts,shifts))
    moving_right=max(p[1][2]+dx+p[0].width*.04 for p,dx in zip(parts,shifts))
    bounds=(max(0,moving_left),max(0,top),min(w,moving_right),min(h,bottom))
    return apply_camera(canvas,bounds,plan,t) if camera else canvas.convert('RGB')


def motion_prompt(scene):
    # The episode palette may mention night/rain; choose actions from the current
    # lyric and literal scene, before the shared world/style suffix.
    if scene.get('visual_action'):
        return scene.get('visual_action')
    return scene.get('lyric','')+' '+scene.get('prompt','').split('. Clear complete main character',1)[0]
