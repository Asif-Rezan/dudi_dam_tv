"""Write original rhyme verses with pinned local Qwen; never fall back to templates."""
import hashlib
import json
import re
from pathlib import Path
from lyrics_cpu import MODEL_ID, request_story, StoryGenerationError

VERSION='qwen-kids-original-v1'
REFRAIN='dudi dudi dam dam dudi dudi dam'


def normalized(text):
    return ' '.join(re.findall(r'[a-z]+',text.lower()))


def verse_lines(song):
    return [normalized(s['lyric']) for s in song['scenes'] if normalized(s['lyric']) != REFRAIN]


def novelty_reason(lines, history):
    """Ignore the intentionally shared refrain, compare real verse content."""
    if len(set(lines)) != len(lines):
        return 'repeated_verse_in_episode'
    def grams(items):
        return {tuple(words[i:i+4]) for line in items for words in [line.split()] for i in range(len(words)-3)}
    current=grams(lines)
    for entry in history:
        previous=entry.get('verse_lines',[])
        if not previous:
            continue
        if set(lines)==set(previous):
            return 'duplicate_verses'
        old=grams(previous)
        if current and old and len(current & old)/min(len(current),len(old)) > .35:
            return 'similar_verses'
    return None


def request_json(schema, prompt, seed, budget=2600):
    response=request_story('chat/completions',{'model':MODEL_ID,'seed':seed,'temperature':.85,
        'max_completion_tokens':budget,'bounded_metadata_fields':['description','title'],
        'messages':[{'role':'system','content':'You write original, gentle, joyful English nursery rhymes for ages 2-6. Return the requested JSON only. Never reuse a stock verse or a known song.'},
                    {'role':'user','content':prompt}],
        'response_format':{'type':'json_schema','json_schema':{'name':'kids_rhyme','schema':schema}}})
    return json.loads(response['choices'][0]['message']['content'])


def write_rhyme(day, identity, seconds, history, draft_path=None):
    path=Path(draft_path) if draft_path else None
    state=json.loads(path.read_text()) if path and path.exists() else {}
    if state and (state.get('writer_version'),state.get('run_id'),state.get('duration')) != (VERSION,identity,seconds):
        raise ValueError('Saved draft uses another identity or writer; start a fresh run ID')
    def save():
        if path:
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(state,ensure_ascii=False,indent=2))
            temp.replace(path)
    base=int(hashlib.sha256(identity.encode()).hexdigest()[:8],16)%(2**31-10000)
    chapters=(seconds+119)//120
    recent=[{'title':h.get('title',''),'story':h.get('story_summary','')} for h in history[-12:]]
    outline_schema={'type':'object','additionalProperties':False,'required':['title','story_summary','description','chapters'],
        'properties':{'title':{'type':'string','minLength':8,'maxLength':65},
        'story_summary':{'type':'string','minLength':40,'maxLength':400},
        'description':{'type':'string','minLength':80,'maxLength':650},
        'chapters':{'type':'array','minItems':chapters,'maxItems':chapters,'items':{'type':'string','minLength':20,'maxLength':180}}}}
    # If a complete candidate is too similar, rewrite it with another seed.
    for attempt in range(state.get('attempt',0),3):
        if not state.get('outline'):
            state=dict(writer_version=VERSION,run_id=identity,duration=seconds,attempt=attempt,sections=[])
            save()  # Preserve identity and retry state even if the first response fails.
            state['outline']=request_json(outline_schema,
                f'Create a NEW {seconds//60}-minute nursery rhyme episode for Dudi Dum TV on {day}. '
                f'Creative identity {identity}; variation {attempt}. Invent a distinct adventure with a yellow duckling and white bunny. '
                f'Write {chapters} connected chapter ideas with a beginning, discoveries and a happy ending. '
                'Teach gentle movement, kindness, colors or nature through concrete playful actions. '
                'English title must name the actual new adventure, not a run ID. Write a concise 2-3 sentence description, 40-65 words and under 600 characters, describing this particular story. '
                'Avoid scary situations, danger, commercial brands, adult themes, requests to subscribe and copying existing songs. '
                'Do not repeat these recent titles or story premises: '+json.dumps(recent),base+attempt*100)
            save()
        outline=state['outline']
        prior=[row['lyric'] for section in state['sections'] for row in section]
        for chapter in range(len(state['sections']),chapters):
            count=min(12,(seconds-chapter*120+9)//10)
            schema={'type':'object','additionalProperties':False,'required':['verses'],'properties':{
                'verses':{'type':'array','minItems':count,'maxItems':count,'items':{
                    'type':'object','additionalProperties':False,'required':['lyric','visual'],
                    'properties':{'lyric':{'type':'string','minLength':10,'maxLength':100},
                                  'visual':{'type':'string','minLength':15,'maxLength':180}}}}}}
            for retry in range(3):
                block=request_json(schema,
                    f'Write {count} NEW short English sung lines for chapter {chapter+1}/{chapters} of this original episode: '
                    +json.dumps(outline)+'. Current chapter: '+outline['chapters'][chapter]+'. '
                    'Each line occupies five seconds: use 4-9 simple singable words with playful rhyme and concrete actions. '
                    f'Between every two original lines the singer will sing "{REFRAIN}" for five seconds. '
                    'Do not put that refrain in your output; the arranger inserts it. '
                    'Every verse line must be different. Develop this chapter rather than repeating earlier verses. '
                    'For each line, visual describes the same action and setting, featuring the same duckling and bunny. '
                    'It is a text-free cartoon picture prompt, with no camera instructions or lettering. '
                    'Previous lines to avoid repeating: '+json.dumps(prior[-24:])+f'. Rewrite attempt {retry}.',
                    base+attempt*100+chapter*3+retry+1)
                rows=block['verses']
                valid=len(rows)==count and all(4<=len(normalized(row['lyric']).split())<=12 and normalized(row['lyric'])!=REFRAIN for row in rows)
                proposed=[normalized(v) for v in prior]+[normalized(row['lyric']) for row in rows]
                if valid and len(set(proposed))==len(proposed):
                    break
            else:
                raise StoryGenerationError('Qwen could not write distinct singable verse lines')
            state['sections'].append(rows)
            prior.extend(row['lyric'] for row in rows)
            save()
            print(json.dumps({'phase':'original AI verses written','chapter':chapter+1,'chapters':chapters,'verse_lines':len(prior)}),flush=True)
        reason=novelty_reason([normalized(line) for line in prior],history)
        if not reason and not any(h.get('title')==outline['title'] for h in history):
            state['novelty_checked']=True
            save()
            return state
        print(json.dumps({'phase':'rewrite non-original lyrics','reason':reason or 'duplicate_title','attempt':attempt+1}),flush=True)
        state=dict(writer_version=VERSION,run_id=identity,duration=seconds,attempt=attempt+1,sections=[])
        save()
    raise StoryGenerationError('Original rhyme validation failed; template fallback is disabled')
