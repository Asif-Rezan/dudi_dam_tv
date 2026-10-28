import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rhyme_writer import write_rhyme, novelty_reason, normalized, VERSION
from lyrics_cpu import StoryGenerationError

WORDS=['amber','blue','coral','daisy','emerald','fern','golden','hazel','indigo','jolly','kiwi','lemon']

def fake_model(schema,prompt,seed,budget=2600):
    if 'chapters' in schema['properties']:
        count=schema['properties']['chapters']['minItems']
        return {'title':f'The Shimmering Seed Adventure {seed}',
            'story_summary':'Duck and bunny discover a shiny seed and grow a magical garden together.',
            'description':'A playful English rhyme about duck and bunny planting a seed, caring for flowers and sharing kindness.',
            'chapters':[f'Chapter {i}: find a friendly surprise in the garden' for i in range(count)]}
    count=schema['properties']['verses']['minItems']
    # Distinct fixture words, varying with the model request seed.
    signature=''.join(chr(97+int(c,16)) for c in format(seed,'x'))
    return {'verses':[{'lyric':f'{WORDS[i]} friendly {signature} ducklings explore meadow',
                       'visual':f'Duckling and bunny wave beside a {WORDS[i]} flower bed'} for i in range(count)]}

class WriterTests(unittest.TestCase):
    def test_original_ai_requests_and_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as tmp, patch('rhyme_writer.request_json',side_effect=fake_model) as model:
            path=Path(tmp)/'draft.json'
            result=write_rhyme('2026-10-28','one',600,[],path)
            self.assertEqual(model.call_count,6)
            self.assertEqual(sum(map(len,result['sections'])),60)
            self.assertTrue(result['novelty_checked'])
            self.assertEqual(result['writer_version'],VERSION)
            again=write_rhyme('2026-10-28','one',600,[],path)
            self.assertEqual(again,result)
            self.assertEqual(model.call_count,6)
            with self.assertRaises(ValueError): write_rhyme('2026-10-28','another',600,[],path)

    def test_failed_chapter_resumes_without_rewriting_finished_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'draft.json'
            calls=0
            def interrupted(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==4: raise StoryGenerationError('interrupted')
                return fake_model(*args,**kwargs)
            with patch('rhyme_writer.request_json',side_effect=interrupted), self.assertRaises(StoryGenerationError):
                write_rhyme('2026-10-28','resume',480,[],path)
            saved=json.loads(path.read_text())
            self.assertEqual(len(saved['sections']),2)
            with patch('rhyme_writer.request_json',side_effect=fake_model) as model:
                finished=write_rhyme('2026-10-28','resume',480,[],path)
                self.assertEqual(model.call_count,2)
            self.assertEqual(finished['sections'][:2],saved['sections'])

    def test_repeated_lines_fail_without_template_fallback(self):
        def repeated(schema,prompt,seed,budget=2600):
            result=fake_model(schema,prompt,seed)
            if 'verses' in result:
                for row in result['verses']: row['lyric']='Happy little bunny waves hello'
            return result
        with patch('rhyme_writer.request_json',side_effect=repeated), self.assertRaises(StoryGenerationError):
            write_rhyme('2026-10-28','repeat',480,[])

    def test_novelty_compares_verses_not_shared_refrain(self):
        lines=['tiny ducklings carry baskets full of daisies','bunny paints a rainbow across the sky']
        self.assertIsNone(novelty_reason(lines,[]))
        self.assertEqual(novelty_reason(lines,[{'verse_lines':lines}]),'duplicate_verses')
        self.assertEqual(novelty_reason([lines[0],lines[0]],[]),'repeated_verse_in_episode')
        self.assertIsNone(novelty_reason(lines,[{'verse_lines':['gentle sea turtles build castles with sand']}]))

    def test_different_run_ids_produce_different_model_seeds(self):
        with patch('rhyme_writer.request_json',side_effect=fake_model):
            first=write_rhyme('2026-10-28','first',480,[])
            second=write_rhyme('2026-10-28','second',480,[])
        self.assertNotEqual(first['outline'],second['outline'])
        self.assertNotEqual(first['sections'],second['sections'])
