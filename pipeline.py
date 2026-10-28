"""Hindi song -> ACE-Step 1.5 -> HD visualizer -> verified public YouTube video."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from zoneinfo import ZoneInfo
from storage import Store, required


class DuplicateSongError(RuntimeError):
    """A safe diagnostic; never expose raw API responses or checkpoint contents."""


def pipeline_failure_message(error):
    if isinstance(error, DuplicateSongError):
        return ('Pipeline failed [duplicate_song]: lyrics or title already published. '
                'Create a fresh song with a new run ID; do not retry duplicate media.')
    return ('Pipeline failed: ' + type(error).__name__ +
            '. Inspect checkpoint and configuration.')


def song_duplicate_reason(song, history, run_id=None):
    digest = hashlib.sha256(normalize_lyrics(song['lyrics']).encode()).hexdigest()
    entries = [entry for entry in history if run_id is None or entry.get('run') != run_id]
    if any(entry.get('hash') == digest for entry in entries):
        return 'lyrics'
    if any(entry.get('title') == song['title'] for entry in entries):
        return 'title'
    return None


def lyric_title_candidates(lyrics, search_term, year):
    """Bounded public titles from actual sung lines, without model retries."""
    candidates = []
    suffix = f' | {search_term} {year}'
    for line in normalize_lyrics(lyrics).splitlines():
        line = re.sub(r'\[[^]]*\]', '', line).strip()
        words = re.findall(r'[\u0900-\u097f]+', line)
        phrase = ' '.join(words[:6])
        if len(words) < 2 or not phrase:
            continue
        while len(phrase + suffix) > 100 and ' ' in phrase:
            phrase = phrase.rsplit(' ', 1)[0]
        title = phrase + suffix
        if len(title) <= 100 and title not in candidates:
            candidates.append(title)
    return candidates


def normalize_lyrics(text):
    """Repair escaped layout markers without changing the Hindi words."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\\+(?:r\\+n|n|r)', '\n', text)
    return re.sub(r'\\+t', ' ', text)


def validate_song(song):
    for field in ('title', 'lyrics', 'prompt', 'description'):
        if not isinstance(song.get(field), str) or not song[field].strip():
            raise ValueError('Missing song ' + field)
    if len(song['title']) > 100 or len(song['description']) > 4400:
        raise ValueError('YouTube metadata too long')
    song['lyrics'] = normalize_lyrics(song['lyrics'])
    if not re.search(r'[\u0900-\u097f]', song['lyrics']):
        raise ValueError('Hindi Devanagari lyrics required')
    if not 180 <= song.get('duration', 0) <= 360:
        raise ValueError('Song must be 180-360 seconds')
    if 'tags' in song and (not isinstance(song['tags'], list) or
            not all(isinstance(tag, str) and 0 < len(tag.strip()) <= 40 for tag in song['tags'])):
        raise ValueError('Invalid song tags')
    if 'visual_mood' in song and song['visual_mood'] not in ('romance', 'heartbreak', 'healing'):
        raise ValueError('Invalid visual mood')
    if 'thumbnail_text' in song and not re.fullmatch(r'[A-Za-z0-9 !?]{3,26}', song['thumbnail_text']):
        raise ValueError('Invalid thumbnail hook')
    for field in ('background_prompt', 'thumbnail_prompt'):
        if field in song and (not isinstance(song[field], str) or not 40 <= len(song[field]) <= 380):
            raise ValueError('Invalid image prompt')
    return song


SONG_PROFILES = (
    ('romance', 'Hindi romantic acoustic pop', 'new love; an ordinary shared moment becomes unforgettable', 'warm intimate solo vocal, acoustic guitar, piano, gentle live drums', 'TERE SAATH'),
    ('heartbreak', 'Hindi sad piano ballad', 'a quiet goodbye; acceptance rather than blame', 'restrained vulnerable solo vocal, felt piano, cello, spacious drums', 'ADHURI BAATEIN'),
    ('romance', 'Hindi indie dream pop', 'long-distance love; two lives connected by a small daily ritual', 'airy expressive vocal, clean electric guitar, atmospheric synths, soft groove', 'DOOR HOKE BHI'),
    ('healing', 'Hindi uplifting folk pop', 'starting again after loss; rediscovering self-worth', 'grounded hopeful vocal, acoustic guitar, flute, warm percussion', 'PHIR SE JEE LE'),
    ('romance', 'Hindi celebratory dance pop', 'joyful reunion; choosing each other again', 'playful energetic vocal, dholak, bass, bright synths, danceable rhythm', 'DIL KA JASHN'),
    ('heartbreak', 'Hindi ghazal-inspired contemporary ballad', 'unspoken affection; a letter that never reaches its reader', 'measured expressive vocal, harmonium, tabla, sarangi, subtle piano', 'ANKAHI MOHABBAT'),
    ('healing', 'Hindi soulful cinematic pop', 'finding hope in solitude; courage for a new morning', 'soulful solo vocal, piano, strings, gradual percussion build', 'NAYI SUBAH'),
    ('romance', 'Hindi monsoon lo-fi pop', 'remembering a first meeting in the rain', 'soft intimate vocal, mellow keys, muted guitar, relaxed lo-fi beat', 'BAARISH AUR TUM'),
)


def song_profile(day):
    # Calendar rotation works even in the isolated lyrics job, which has no Drive history.
    return SONG_PROFILES[dt.date.fromisoformat(day).toordinal() % len(SONG_PROFILES)]


def vocal_gender_for_day(day):
    # Calendar days, not day-of-month parity: stays alternating across month/leap boundaries.
    anchor = dt.date(2026, 10, 28)
    return ('male', 'female')[(dt.date.fromisoformat(day)-anchor).days % 2]


def make_song(day, history, draft_path=None, generation_id=None, vocal_gender_override='auto'):
    mood, genre, story, arrangement, hook = song_profile(day)
    if vocal_gender_override not in ('auto', 'male', 'female'):
        raise ValueError('Vocal choice must be auto, male or female')
    vocal_gender = (vocal_gender_for_day(day) if vocal_gender_override == 'auto' else vocal_gender_override)
    opposite_gender = 'female' if vocal_gender == 'male' else 'male'
    search_term = {'romance': 'Hindi Romantic Song', 'heartbreak': 'Hindi Sad Song',
                   'healing': 'Heart Touching Hindi Song'}[mood]
    hindi_term = {'romance': 'हिंदी रोमांटिक गाना', 'heartbreak': 'हिंदी दर्द भरा गाना',
                  'healing': 'दिल छू लेने वाला हिंदी गाना'}[mood]
    year = day[:4]
    identity = generation_id or day
    seed = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:4], 'big') % (2**31 - 3)
    places = ('a quiet railway platform', 'a rooftop garden', 'a riverside tea stall',
              'a bookshop at closing time', 'a lantern-lit courtyard', 'a seaside promenade',
              'a mountain bus stop', 'a rain-washed city street')
    objects = ('a folded letter', 'a shared umbrella', 'an old photograph', 'a cup of tea',
               'a handwritten note', 'a train ticket', 'a pressed flower', 'a familiar scarf')
    scene = f'{places[seed % len(places)]}, with {objects[(seed // len(places)) % len(objects)]}'
    prompt = f'''Write an ORIGINAL Hindi song for Heart and Mind on {day}.
    Today's direction: {genre}. Emotional story: {story}.
    Musical arrangement: {arrangement}. Visual mood: {mood}.
    Write for a solo {vocal_gender} singer, using consistent first-person Hindi grammar
    appropriate to that narrator. Do not add singer labels to sung lines.
    Unique creative brief {identity}: set the story around {scene}.
    Use this brief as inspiration only; never include its identifier in public text.
    Develop a specific original scene, characters and emotional progression in this direction.
    Do not recycle a generic love song. Use concrete sensory details, conversational poetic
    Hindi, fresh metaphors, natural breath-length phrases and consistent viewpoint.
    Plan a clear beginning, emotional turn in verse 2, and resolution in the bridge/outro.
    Write a memorable 2-4 line chorus with one distinctive central phrase; repeat that chorus
    consistently. Verses should advance the story, not paraphrase the chorus. Keep a singable
    syllable pattern within each section; avoid forced rhyme, filler and unrelated imagery.
    Structure: [Intro] (instrumental, no sung directions), [Verse 1] (4 lines),
    [Pre-Chorus] (2), [Chorus] (4), [Verse 2] (4), [Chorus] (same 4),
    [Bridge] (2-4), [Final Chorus] (same 4), [Outro] (2).
    Target 180-220 sung words for a focused 3 to 3.5 minute album song.
    Keep most lines 5-8 words, with balanced lengths that fit one melodic phrase.
    The chorus must say something specific and emotionally meaningful, not repeat only
    a two-word title. Establish a clear melodic hook and repeat its wording exactly.
    Verse 1 shows one moment; verse 2 changes the situation; the bridge reveals a decision.
    Use idiomatic everyday Hindi, correct verb agreement and consistent तू/तुम/आप usage.
    Never translate English phrases literally or insert words such as फोल्ड लेटर or लाइट्स.
    Prefer familiar natural Hindi over ornate vocabulary and vague philosophical filler.
    Read every line as spoken Hindi first: if it sounds unnatural, rewrite it before singing.
    पूरा गीत हिंदी की देवनागरी लिपि में लिखो। रोमन लिपि में हिंदी मत लिखो।
    Every sung line must use Devanagari, never English transliteration; bracket labels in English.
    Never copy existing lyrics, melodies, titles, or imitate a named singer.
    Avoid these previous titles: {json.dumps([entry['title'] for entry in history if entry.get('title')], ensure_ascii=False)}.
    Return JSON only with these fields:
    title: original Hindi song name first, a short Romanized Hindi name, then the accurate
      search phrase "{search_term} {year}". Keep the whole title <=100 characters, ideally 65-90.
      Format example ONLY: तेरे बिना | Tere Bina | Hindi Sad Song {year}.
      Use the supplied mood's search phrase; do not label a hopeful song sad or a ballad dance.
      Never claim a film connection, famous singer, official release, viral hit or chart success.
    lyrics: complete song as above. Musical production directions are supplied separately;
      do not return a prompt field.
    duration: integer seconds 180-210, aim 195.
    No spoken CTA. Keep the song focused: 180-220 sung words, including repeated choruses.
    Do not add metadata, descriptions, tags or image prompts to this response.
    Privately revise for originality, story, meter and singability before returning.'''
    from lyrics_cpu import MODEL_ID, request_story
    core_schema = {'type': 'object', 'additionalProperties': False,
        'required': ['title', 'lyrics', 'prompt', 'duration'],
        'properties': {
            'title': {'type': 'string', 'minLength': 1, 'maxLength': 100},
            'lyrics': {'type': 'string', 'minLength': 500, 'pattern': '[ऀ-ॿ]'},
            'prompt': {'type': 'string', 'minLength': 20, 'maxLength': 600},
            'duration': {'type': 'integer', 'minimum': 180, 'maximum': 360},
            'vocal_gender': {'type': 'string', 'enum': ['male', 'female']},
            'song_date': {'type': 'string', 'pattern': r'^\d{4}-\d{2}-\d{2}$'}}}
    # Production directions are controlled input, not creative prose. Keeping them
    # outside the completion prevents maxLength retries from discarding good lyrics.
    tempos = (86, 72, 92, 96, 112, 76, 82, 80)
    bpm = tempos[SONG_PROFILES.index(song_profile(day))]
    production_prompt = (f'Solo {vocal_gender} lead vocal; no {opposite_gender} singer or duet. '
        f'{genre}; {arrangement}; {bpm} BPM, 4/4. '
        'Warm melodic tone, natural Hindi diction, legato phrasing. '
        'Vocal entry within 8s; catchy chorus by 40s. Intimate verses, lifted chorus, '
        'sparse bridge, final chorus, resolved ending. Vocal-forward balanced mix, '
        'warm bass, restrained reverb; no speech or long solos.')
    generation_schema = dict(core_schema, required=['title', 'lyrics', 'duration'],
        properties={key: value for key, value in core_schema['properties'].items()
                    if key in ('title', 'lyrics', 'duration')})
    def request(instructions, schema, tokens, seed_offset=0):
        result = request_story('chat/completions', {'model': MODEL_ID,
            'messages': [{'role': 'system', 'content': 'You are an original Hindi songwriter and truthful music editor. Write natural, singable Hindi in Devanagari.'},
                         {'role': 'user', 'content': instructions}],
            'response_format': {'type': 'json_schema', 'json_schema': {'schema': schema}},
            'max_completion_tokens': tokens, 'seed': (seed + seed_offset) % (2**31 - 3)})
        return json.loads(result['choices'][0]['message']['content'])

    # Keep the full song and packaging out of the same completion. Small CPU models
    # otherwise have to satisfy many tight text bounds while writing long Hindi lyrics.
    from jsonschema import Draft202012Validator
    fresh_core = not (draft_path is not None and draft_path.exists())
    if not fresh_core:
        song = json.loads(draft_path.read_text())
        Draft202012Validator(core_schema).validate(song)
        if vocal_gender_override != 'auto' and song.get('vocal_gender') != vocal_gender_override:
            raise ValueError('Saved song voice differs from the request; use a new run ID')
    else:
        song = request(prompt, generation_schema, 6000)
        song['prompt'] = production_prompt
        song['vocal_gender'] = vocal_gender
        song['song_date'] = day
        # Keep the new lyric form matched to a focused 3m15s arrangement.
        song['duration'] = 195
        Draft202012Validator(core_schema).validate(song)
        song['lyrics'] = normalize_lyrics(song['lyrics'])
    if draft_path is not None:
        temporary = draft_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(song, ensure_ascii=False, indent=2))
        temporary.replace(draft_path)
    if song_duplicate_reason(song, history) == 'lyrics':
        raise DuplicateSongError()
    # Saved cores retain their original voice, even when retried on the next calendar day.
    editorial_voice = song.get('vocal_gender')
    narrator_instruction = (f'Keep the first-person narrator consistent with a solo {editorial_voice} singer.'
                            if editorial_voice else 'Preserve the original narrator and grammatical gender.')
    # A separate editorial pass catches grammatical Hindi that can satisfy JSON
    # validation while remaining awkward to sing. Checkpoint it across metadata retries.
    quality_path = draft_path.with_name('lyrics-quality.json') if draft_path is not None else None
    lyric_hash = hashlib.sha256(song['lyrics'].encode()).hexdigest()
    quality = json.loads(quality_path.read_text()) if quality_path is not None and quality_path.exists() else {}
    if (fresh_core or quality.get('version') == 1) and quality.get('lyrics_hash') != lyric_hash:
        if quality_path is not None:
            quality_path.write_text(json.dumps({'version': 1, 'lyrics_hash': None}))
        edit_schema = {'type': 'object', 'additionalProperties': False, 'required': ['lyrics'],
            'properties': {'lyrics': core_schema['properties']['lyrics']}}
        edit_prompt = f'''Act as a meticulous native Hindi lyric editor, then a vocal arranger.
        Polish this original song for {genre}. Preserve its story, viewpoint, emotional turn
        and distinctive hook. Return only lyrics, never commentary, credits or translations.
        Fix unnatural Hindi, literal English translations, tense, gender and verb agreement.
        {narrator_instruction}
        Maintain one form of address (तू or तुम), and a consistent narrator throughout.
        Use everyday idiomatic Hindi, concrete images and clear emotional meaning.
        Remove nonsensical metaphors, filler and unnatural loanwords. Do not merely swap synonyms.
        Each line must make sense when spoken aloud and be comfortable to sing in one breath.
        Aim 5-8 words per line with comparable lengths within each section, without forced rhyme.
        Keep a distinctive four-line chorus, repeated exactly, that expresses the central feeling.
        Verse 2 must advance the story; the short bridge changes perspective or makes a decision.
        Use [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Chorus], [Bridge],
        [Final Chorus], [Outro]. All sung words in Devanagari. No directions outside brackets.
        Aim 180-220 sung words including repetitions. Do not expand into a long poem.
        Privately check grammar, meaning, repetition and singability before returning.
        Original lyrics: {song['lyrics']}'''
        song['lyrics'] = normalize_lyrics(request(edit_prompt, edit_schema, 5000, 100)['lyrics'])
        if draft_path is not None:
            temporary = draft_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(song, ensure_ascii=False, indent=2))
            temporary.replace(draft_path)
            quality = {'version': 1, 'lyrics_hash': hashlib.sha256(song['lyrics'].encode()).hexdigest()}
            temporary = quality_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(quality))
            temporary.replace(quality_path)
    # Check saved cores too: resumed artifacts may predate the current history.
    # A title-only correction keeps good lyrics instead of regenerating the music.
    if song_duplicate_reason(song, history) == 'lyrics':
        raise DuplicateSongError()
    avoided_titles = [entry['title'] for entry in history if entry.get('title')]
    if song['title'] in avoided_titles:
        # Models can repeat a rejected title despite instructions and new seeds.
        # Select a real sung phrase instead; no random suffix or internal run ID.
        candidates = lyric_title_candidates(song['lyrics'], search_term, year)
        song['title'] = next((title for title in candidates if title not in avoided_titles), '')
        if not song['title']:
            raise DuplicateSongError()
        print(json.dumps({'phase': 'title conflict recovered', 'source': 'song lyrics'}), flush=True)
    if draft_path is not None:
        temporary = draft_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(song, ensure_ascii=False, indent=2))
        temporary.replace(draft_path)
    packaging_schema = {'type': 'object', 'additionalProperties': False,
        'required': ['description', 'tags', 'thumbnail_text', 'background_prompt', 'thumbnail_prompt'],
        'properties': {
            'description': {'type': 'string', 'minLength': 20, 'maxLength': 1200},
            'tags': {'type': 'array', 'minItems': 8, 'maxItems': 12,
                     'items': {'type': 'string', 'minLength': 1, 'maxLength': 40}},
            'thumbnail_text': {'type': 'string', 'minLength': 3, 'maxLength': 26, 'pattern': '^[A-Za-z0-9 !?]+$'},
            'background_prompt': {'type': 'string', 'minLength': 40, 'maxLength': 380},
            'thumbnail_prompt': {'type': 'string', 'minLength': 40, 'maxLength': 380}}}
    packaging_prompt = f'''Package the supplied original Hindi song. Do not rewrite the song.
    Genre: {genre}. Visual mood: {mood}. Return only these five JSON fields.
    description: 60-100 words, readable Hindi and English. The first 150 characters must
      naturally include this song's name and "{search_term}". The first two lines should explain
      its specific emotion/story and include "{hindi_term}". Then give one natural listening
      context and an honest sentence about the arrangement. Include "new Hindi song {year}"
      and "original Hindi music" only once each where they fit naturally. Do not repeat a list
      of keywords. No invented artist/label credits, external links, technical explanations,
      internal tool names, model names, providers or software names. Do not add hashtags or
      production credits; the publisher adds the channel credit and three relevant hashtags.
    tags: 8-12 distinct relevant search phrases, each <=40 characters. Prioritize this song's
      short Devanagari name, Romanized name, "{search_term}", "{hindi_term}",
      "new Hindi song {year}", the actual musical genre, one suitable listening context,
      "original Hindi music", and "Heart and Mind". Use specific Hindi/English searches,
      not broad unrelated self-help terms. No other singers, films, tools, models or trend bait.
    thumbnail_text: 2-4 familiar Romanized Hindi words, <=26 ASCII characters, expressing
      the chorus's emotional promise. Use natural Hindi transliteration, never mixed English
      slogans such as MILE AGAIN. Prefer a complete relatable phrase over generic love labels.
      Complement the title instead of copying it. No channel name, fake claims or punctuation bait.
      Mood reference only, do not copy mechanically: {hook}.
    background_prompt: 16-22 English words describing one beautiful, lyric-specific music-video scene.
      Show the emotional action and the actual location, weather, meaningful prop and light from these lyrics.
      Romance: a beautiful South Asian adult couple sharing a tender moment. Separation: the same young
      adult couple visibly apart, with quiet longing. Healing: a beautiful young adult South Asian woman
      in a hopeful moment. All adults are 25-35, fully clothed; use original fictional faces.
      Use a medium-wide environmental view with recognizable people, scenic depth and a clear lower edge
      for the waveform. Natural skin, soft diffused face light, balanced warm/cool color and an uncluttered
      scene. Keep both people within the frame. No enormous cropped male face, elderly man, copied actor,
      vintage poster, collage, title lettering, captions, logos or watermarks.
    thumbnail_prompt: a DIFFERENT 16-22 word English scene selling this song's real emotional promise.
      Romance: exactly one beautiful young adult South Asian couple, tender eye contact or a joyful reunion.
      Separation: exactly that adult couple with readable longing and a little distance; no fake cheerful
      romance or exaggerated tears. Healing: one beautiful young adult South Asian woman with hopeful relief.
      All adults are 25-35, naturally expressive and fully clothed. Close chest-up framing, both couple
      faces clearly separated, sharp eyes, soft natural skin light and a softly blurred lyric-specific setting.
      One clear emotional moment that reads at phone size; no unrelated older man, collage or busy props.
      Use the full frame for the scene; no blank typography panel, no red paint strokes.
      This is a TEXT-FREE photograph: no Hindi, Romanized Hindi or English lettering, song title, hook,
      year, badge, logo, watermark or signature. Do not ask the image model to draw writing.
      The thumbnail_text field is retained only as metadata and for the existing video overlay;
      it is never rendered on the thumbnail or sent to the image model.
    Description: 60-100 words maximum. Tags must EACH be 40 characters or fewer.
    The thumbnail hook must contain ONLY ASCII English letters, spaces, ! or ?; no Devanagari.
    Keep both scene prompts under 380 characters each. Do not repeat lyrics in the response.
    Song to package: {json.dumps(song, ensure_ascii=False)}'''
    song['lyrics'] = normalize_lyrics(song['lyrics'])
    song.update(request(packaging_prompt, packaging_schema, 3000))
    song['visual_mood'] = mood  # Chosen locally, never ask the model to reproduce a fixed enum.
    return validate_song(song)


PUBLIC_INTERNAL_NAMES = re.compile(r'(?i)\b(?:ace[- ]?step|ssd[- ]?1b|segmind|qwen[\w.-]*|whisper|diffusers|hugging\s*face|llama|openai|gpt[- ]?\d|github actions)\b')


def upload_description(song):
    """Keep the song summary public, with only verified channel credit and hashtags."""
    text = re.sub(r'#[^\s#]+', '', song['description'])
    sentences = re.split(r'(?<=[.!?।])\s+|\n+', text)
    sentences = [part.strip() for part in sentences if part.strip() and
        not PUBLIC_INTERNAL_NAMES.search(part) and
        not re.search(r'(?i)(?:created|produced|sung|composed|music|lyrics|vocals)\s+(?:by|:)', part)]
    mood = song.get('visual_mood', 'romance')
    hashtag = {'romance': '#HindiRomanticSong', 'heartbreak': '#HindiSadSong',
               'healing': '#HeartTouchingSong'}.get(mood, '#HindiMusic')
    return ('\n'.join(sentences) + '\n\nOriginal Hindi music by Heart and Mind.\n\n'
            '#HindiSong #HindiMusic ' + hashtag)


def metadata_tags(song):
    # Old saved songs remain publishable; new songs carry their own search terms.
    candidates = song.get('tags', []) + ['Heart and Mind', 'Hindi song', 'original Hindi music']
    result = []
    for tag in candidates:
        tag = tag.strip()
        if tag and not PUBLIC_INTERNAL_NAMES.search(tag) and tag.casefold() not in {item.casefold() for item in result}:
            # YouTube counts quotes around tags containing spaces toward its 500-character limit.
            if sum(len(item) + (2 if ' ' in item else 0) + 1 for item in result + [tag]) <= 480:
                result.append(tag)
    return result


def duration(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=nw=1:nk=1', str(path)], text=True))


def validate_duration(seconds):
    if not 180 <= seconds <= 360:
        raise ValueError('Measured song/video duration outside 3-6 minutes')


def render(root):
    from artwork import create_artwork
    song = json.loads((root/'song.json').read_text())
    create_artwork(root, song)
    subprocess.run(['ffmpeg', '-y', '-loop', '1', '-i', str(root/'cover.png'), '-i', str(root/'song.wav'),
        '-filter_complex', '[1:a]asplit=2[a][v];[v]showwaves=s=1600x90:mode=line:colors=0xf9b4cc:rate=25,format=rgba[w];[0:v][w]overlay=160:980:shortest=1,format=yuv420p[out]',
        '-map', '[out]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
        '-c:a', 'aac', '-b:a', '320k', '-t', str(duration(root/'song.wav')), '-shortest', '-movflags', '+faststart', str(root/'video.mp4')],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    validate_duration(duration(root/'video.mp4'))


def youtube_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    client = build('youtube', 'v3', credentials=Credentials.from_authorized_user_info(
        json.loads(required('YOUTUBE_TOKEN_JSON'))), cache_discovery=False)
    items = client.channels().list(part='id,snippet', mine=True).execute().get('items', [])
    expected = required('EXPECTED_CHANNEL_ID')
    if len(items) != 1 or items[0]['id'] != expected:
        raise RuntimeError('Wrong YouTube channel; select Heart and Mind')
    return client


def publish(client, root, song, state, save):
    from googleapiclient.http import MediaFileUpload
    if not state.get('video_id'):
        if state.get('upload_started'):
            raise RuntimeError('Ambiguous upload; reconcile YouTube before retry to avoid duplicates')
        state['upload_description'] = upload_description(song)
        state['upload_started'] = True
        save()
        request = client.videos().insert(part='snippet,status', body={
            'snippet': {'title': song['title'], 'description': state['upload_description'],
                'categoryId': '10', 'defaultLanguage': 'hi', 'defaultAudioLanguage': 'hi',
                'tags': metadata_tags(song)},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False,
                       'containsSyntheticMedia': True}},
            media_body=MediaFileUpload(str(root/'video.mp4'), resumable=True, chunksize=8*1024*1024))
        result = None
        while result is None:
            _, result = request.next_chunk(num_retries=5)
        state['video_id'] = result['id']
        save()
    if not state.get('thumbnail_uploaded'):
        client.thumbnails().set(videoId=state['video_id'],
            media_body=MediaFileUpload(str(root/'thumbnail.jpg'))).execute()
        state['thumbnail_uploaded'] = True
        save()
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        items = client.videos().list(part='snippet,status,processingDetails,contentDetails',
                                    id=state['video_id']).execute().get('items', [])
        if not items:
            raise RuntimeError('Uploaded video unavailable')
        video = items[0]
        if video['snippet']['channelId'] != required('EXPECTED_CHANNEL_ID'):
            raise RuntimeError('Uploaded channel mismatch')
        status = video['status']
        if status.get('uploadStatus') in ('failed', 'rejected', 'deleted'):
            raise RuntimeError('YouTube rejected upload')
        if status.get('privacyStatus') != 'public':
            raise RuntimeError('YouTube did not retain public visibility; inspect project/channel restrictions')
        if status.get('uploadStatus') == 'processed' and video.get('contentDetails', {}).get('definition') == 'hd':
            state['phase'] = 'published'
            save()
            return
        time.sleep(20)
    raise TimeoutError('HD processing pending; rerun same run ID')


def run(run_id, defer_drive_cleanup=False):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run ID')
    root = Path('output')/run_id
    root.mkdir(parents=True, exist_ok=True)
    store = Store()
    client = youtube_client()  # Verify accounts before expensive generation.
    key = f'runs/{run_id}/state.json'
    state = store.load(key, {})
    save = lambda: store.save(key, state)
    history = store.load('history.json', [])
    if state.get('phase') == 'published':
        if not any(h['run'] == run_id for h in history):
            history.append({'run': run_id, 'title': state['song']['title'],
                            'hash': state['hash'], 'video_id': state['video_id']})
            store.save('history.json', history)
        if not defer_drive_cleanup:
            from cleanup_drive import cleanup
            cleanup(store, client, run_id, state)
        print('Already published: ' + state['video_id'])
        return
    if not state.get('song'):
        day = dt.datetime.now(ZoneInfo('Asia/Dhaka')).date().isoformat()
        song = (validate_song(json.loads((root/'song.json').read_text()))
                if (root/'song.json').exists() else make_song(day, history, root/'song-draft.json', generation_id=run_id))
        digest = hashlib.sha256(song['lyrics'].encode()).hexdigest()
        if song_duplicate_reason(song, history, run_id):
            raise DuplicateSongError()
        state.update(song=song, hash=digest)
        save()
    song = validate_song(state['song'])
    (root/'song.json').write_text(json.dumps(song, ensure_ascii=False, indent=2))
    if not (root/'song.wav').exists():
        fid = store.find(f'runs/{run_id}/song.wav')
        if fid:
            store.download(fid, root/'song.wav')
        else:
            from music_cpu import generate
            generate(song, root/'song.wav', state, save)
    validate_duration(duration(root/'song.wav'))
    if not state.get('video_id'):
        store.upload(root/'song.wav', f'runs/{run_id}/song.wav')
        if not (root/'video.mp4').exists():
            from song_images import generate_song_images
            generate_song_images(root, song)
            render(root)
        validate_duration(duration(root/'video.mp4'))
        for name in ('song.json', 'video.mp4', 'thumbnail.jpg', 'background-source.png', 'thumbnail-source.png', 'image-manifest.json'):
            if (root/name).exists():
                store.upload(root/name, f'runs/{run_id}/{name}')
    elif not (root/'thumbnail.jpg').exists():
        store.download(store.find(f'runs/{run_id}/thumbnail.jpg'), root/'thumbnail.jpg')
    publish(client, root, song, state, save)
    if not any(h['run'] == run_id for h in history):
        history.append({'run': run_id, 'title': song['title'], 'hash': state['hash'], 'video_id': state['video_id']})
        store.save('history.json', history)
    if not defer_drive_cleanup:
        from cleanup_drive import cleanup
        cleanup(store, client, run_id, state)
    print(json.dumps({'phase': state['phase'], 'video_id': state['video_id']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--defer-drive-cleanup', action='store_true',
                        help='Leave verified media cleanup to the separate workflow job')
    args = parser.parse_args()
    try:
        run(args.run_id, defer_drive_cleanup=args.defer_drive_cleanup)
    except Exception as error:
        # Avoid leaking OAuth/API credentials through raw exception response bodies.
        print(pipeline_failure_message(error))
        raise SystemExit(1)
