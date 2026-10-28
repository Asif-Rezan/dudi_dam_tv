import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from prepare_music import prepare
from kids_rhymes import REFRAIN
from rhyme_writer import VERSION


def fixture_song():
    scenes=[]
    for i in range(96):
        # Test data only; each original line remains distinguishable after normalization.
        suffix=chr(97+(i//2)//26)+chr(97+(i//2)%26)
        scenes.append(dict(index=i,start=i*5,end=(i+1)*5,
            lyric=REFRAIN if i%2 else f'Little {suffix} ducklings gather purple daisies',prompt='Friendly duckling and bunny exploring a bright flower garden'))
    return dict(title='A Brand New Daisy Adventure',description='Friendly ducklings discover bright flowers and learn to care for a gentle garden.',
        prompt='Female nursery rhyme',duration=480,vocal_gender='female',story_summary='A duck and bunny plant daisies together.',
        lyric_writer={'version':VERSION},scenes=scenes,lyrics='\n'.join(s['lyric'] for s in scenes))

class PrepareOriginalTests(unittest.TestCase):
    def test_history_is_checked_and_reserved_before_music_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=os.getcwd();os.chdir(tmp)
            self.addCleanup(os.chdir,old)
            store=Mock(); store.load.return_value=[]
            with patch('storage.Store',return_value=store),patch('prepare_music.make_song',return_value=fixture_song()) as writer,patch('prepare_music.generate') as music:
                prepare('original-test',stage='lyrics',check_history=True)
                music.assert_not_called()
                writer.assert_called_once()
                key,entries=store.save.call_args.args
                self.assertEqual(key,'lyrics-history.json')
                self.assertEqual(len(entries[0]['verse_lines']),48)
                self.assertEqual(entries[0]['run'],'original-test')
                saved=json.loads(Path('output/original-test/song.json').read_text())
                self.assertEqual(saved['lyric_writer']['version'],VERSION)

    def test_old_template_checkpoint_is_not_accepted_as_new_ai_lyrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=os.getcwd();os.chdir(tmp)
            self.addCleanup(os.chdir,old)
            root=Path('output/legacy');root.mkdir(parents=True)
            song=fixture_song();song.pop('lyric_writer')
            (root/'song.json').write_text(json.dumps(song))
            with self.assertRaises(ValueError):prepare('legacy',stage='lyrics')
