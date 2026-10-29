"""Owner-supplied public metadata shared by long videos and Shorts."""
import json
from pathlib import Path

METADATA = Path(__file__).with_name('upload_metadata.json')


def fixed_metadata():
    metadata = json.loads(METADATA.read_text())
    if not isinstance(metadata.get('title'), str) or not 1 <= len(metadata['title']) <= 100:
        raise ValueError('Fixed upload title must contain 1-100 characters')
    if not isinstance(metadata.get('description'), str) or len(metadata['description']) > 5000:
        raise ValueError('Fixed upload description exceeds 5000 characters')
    if metadata.get('tags') != []:
        raise ValueError('Fixed uploads require blank tags')
    return metadata
