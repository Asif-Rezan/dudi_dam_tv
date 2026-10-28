# Dudi Dam TV — kids rhyme video automation

Copied from [Heart-and-Mind](https://github.com/Asif-Rezan/Heart-and-Mind) at `0fca9240b5edf786f09a806401a62dcc386eb0f6`. The first repository commit is the unchanged copy. The kids adaptation retains pinned CPU music/image inference, resumable artifacts, Google account setup, verified YouTube publishing and exact-file Drive cleanup.

## Current behavior

- Default: 600 seconds. Set `VIDEO_DURATION_SECONDS` to 480–720 in five-second steps.
- Sweet adult female singing voice requested, original AI-written English verses alternating with **dudi dudi dam dam dudi dudi dam**. This phrase is a sung refrain, not musical chord notation.
- The first lyrics job runs the pinned local Qwen3-4B CPU model to write a fresh adventure outline, new English verses, and matching visual descriptions. Only the Dudi refrain is fixed. There is no template fallback. Each run ID uses a different generation seed.
- A new SSD-1B cartoon illustration for every five seconds (96–144 images), plus a thumbnail. Sixteen image workers split generation and checkpoint each completed image.
- ACE-Step generates separate sections up to 120 seconds, then FFmpeg joins them. Music is not looped or padded. Short or incorrectly sized sections fail. Section joins and voice/character consistency need listening/viewing review.
- A 30-second excerpt of the user-supplied MP3 is included at `assets/reference/style-reference.mp3`; the full original is not committed. The pinned API exposes `reference_audio`. Inference receives the excerpt for style conditioning; actual influence and singing quality require a model run. Set `REFERENCE_AUDIO_PATH` to a different local file or leave unset to generate without conditioning. Use reference material you have permission to use.
- Storyboard lyrics drive image actions and the pictures change exactly every five seconds. Singing is generative: this is planned timing, **not forced alignment or transcription**. Precise word-level synchronization is not yet implemented.

## Generate before connecting Google

Run **Dudi Dam TV kids rhyme generation** from GitHub Actions with a new `run_id`. The lyrics job checks and reserves lyric originality in private Drive history; connected Drive credentials are required for the production workflow. Local generation without history can run without Google credentials. Download `kids-video-RUN_NUMBER` for the MP4, thumbnail and song/storyboard JSON. Generation is computationally expensive and has not yet been verified end to end on Actions. Existing model revisions and CPU dependencies come from the reference; 120-second sections reload the model for bounded worker isolation. Model memory/time limits may require a larger runner.

Automatic scheduling is off unless repository variable `AUTOMATION_ENABLED=true`. Publishing requires `PUBLISH_ENABLED=true`. The scheduled time inherited from the reference is 03:00 Asia/Dhaka. The workflow defaults to 600 seconds; adjust `VIDEO_DURATION_SECONDS` in its workflow-level env for other durations.

For local AI lyric writing (downloads the pinned Qwen GGUF model):

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-lyrics.txt
python prepare_music.py --run-id first-rhyme --stage lyrics
```

Image preparation also requires CPU PyTorch and `requirements-images-cpu.txt`. Music preparation needs CPU torch/torchaudio, `requirements-music-cpu.txt` and ACE-Step source at revision `ca1e85fe9430179831e6bc6be790c332190a3866` in `.vendor/ace-step`. See the workflow for exact installation. Install FFmpeg for audio joining and video rendering.

## Connect later

1. Configure a Google Cloud OAuth client with YouTube Data API v3 and Google Drive API enabled.
2. Use `python setup_accounts.py --help` for the inherited account setup commands targeting `Asif-Rezan/dudi_dam_tv`. Drive remains restricted to the account in `storage.py`; update it deliberately if using another owner.
3. Add secrets `YOUTUBE_TOKEN_JSON`, `EXPECTED_CHANNEL_ID`, `DRIVE_TOKEN_JSON`, `DRIVE_FOLDER_ID`. Create a new Dudi Dam TV Drive folder with the `dudi_dam_tv_root=v1` application property via setup; do not reuse the reference channel folder.
4. After reviewing a downloaded preview, set `PUBLISH_ENABLED=true`. Uploads declare `selfDeclaredMadeForKids=true`; the configured channel ID must match. Drive stores the scene sources/manifests as `storyboard.tar.gz`, and cleanup removes media only after verified public HD publication.

Google OAuth and the dedicated Drive folder can be checked with the **Verify Google connections** workflow. This only verifies identity, folder privacy and refresh tokens; it does not upload videos. No finished music/video is claimed until inference succeeds and the result is reviewed.

## Verification

`python -m unittest -v` covers duration boundaries, complete contiguous storyboards, cache/shard coverage, missing scene failures, rendering arguments and inherited guarded Drive cleanup. Original reference tests remain in `reference_tests/` as historical specifications; their adult-music assumptions do not describe this adaptation.

## Upload details and scheduling

The workflow dispatch form exposes `upload_mode` (`public` or `scheduled`), `publish_at`, `video_language`, `audio_language`, and `category_id`. Scheduled times must include a timezone (for example `2026-11-01T18:00:00+06:00`) and still be in the future when the upload starts. Allow enough time for generation. With an explicit timestamp, a scheduled upload is private with `publishAt` set; it is verified as scheduled after HD processing. Reusing its run ID checks the same upload rather than creating another one.

`upload_settings.json` stores explicit defaults for English metadata/audio, Music category (10), made for kids, AI disclosure, standard YouTube license, embedding, public statistics, subscriber notifications, and no paid placement. The kids and AI disclosures are enforced for this pipeline. Title, description, tags and thumbnail come from the generated song artifact. Review/edit that artifact before publishing if needed. Comments, cards/end screens and some other Studio-only features are subject to made-for-kids restrictions and are not exposed by this uploader.

Scheduled media is retained on Drive. After its release, rerun the same publishing identity to verify public HD status before cleanup. OAuth Production status removes testing-mode token expiry; it does not guarantee that Google will never revoke a refresh token. Actual upload acceptance/public visibility is always checked rather than assumed from OAuth status.


## Daily 6 AM New York releases

Daily generation starts at 21:00 UTC (03:00 Asia/Dhaka). Once each video finishes uploading, it is scheduled for the first **06:00 America/New_York** slot at least **72 elapsed hours after upload completion**. New York daylight saving changes are handled by the IANA timezone database. The actual wait is 72 hours up to the next qualifying 6 AM slot (normally less than 96 hours). There is an initial three-plus-day buffer before the first release; generation failures/delays can leave gaps.

The default upload is private without a publication timestamp. After YouTube returns its video ID, the pipeline records upload completion, computes and saves the target, then updates YouTube `status.publishAt`. Retry attempts reuse the saved target rather than delaying it again. This step needs `youtube.force-ssl` authorization in addition to the existing upload/read scopes. Default workflow mode is `scheduled` and `publish_at` is empty, so both daily and manual runs follow this policy unless explicitly overridden. `AUTOMATION_ENABLED=true` enables daily generation and `PUBLISH_ENABLED=true` enables uploading.


## Animated picture treatment

Every five-second lyric scene now has continuous 25 fps camera motion: gentle alternating horizontal pan, a slow push-in, a small rhythmic pulse and vertical sway. Translucent bubbles drift independently along the edges for foreground depth. A 0.28-second dissolve uses the previous scene's actual final frame, so scene changes do not add time or shift the soundtrack. The original song is muxed once after the silent clips are joined.

This gives still illustrations a lively storybook presentation; it does not rig character limbs or lip-sync mouths. Motion follows the requested 100 BPM arrangement as a visual guide, not measured audio beats. Full videos remain 1920×1080 and 8–12 minutes, with a new illustration every five seconds. Rendering is split into small clips to bound memory. `render-state.json` fingerprints the renderer version and inputs so an old static video is regenerated automatically.

For a local short preview without model inference or publishing, run `python preview_motion.py image1.png image2.png --audio song.wav --output output/motion-preview.mp4`. Preview images/audio are supplied locally and are never used as a production fallback.


## Fresh AI lyrics on each new run

`rhyme_writer.py` calls the pinned Qwen CPU model first for an original episode outline/title/description, then for new five-second verse lines and corresponding scene actions in chapters up to two minutes long. A 10-minute episode has 60 original lines alternating with 60 fixed Dudi refrain lines. Drafts checkpoint after the outline and each chapter; retries with the same run ID resume that story. Use a new run ID to request a new song.

Normalized verse lines and four-word phrase overlap are checked against `lyrics-history.json` in the private Drive folder, excluding the shared refrain. New lyric identities are reserved before music/image jobs start, including scheduled or unfinished episodes. Repeated or overly similar verses trigger rewriting, then failure if the bounded retries cannot produce a valid result. This is a practical duplicate check, not a guarantee that every possible phrase is globally unique. The workflow installs `requirements-lyrics.txt` and allows 90 minutes for CPU writing; it never substitutes the former template verses on model failure.

Overlong generated titles and descriptions are shortened at word/sentence boundaries before schema validation. Sung lyrics and scene actions are never truncated. Invalid content receives up to three attempts with the failed constraint and actual length supplied to the model. Failure artifacts include an initial draft and `failure.json` with safe error codes and diagnostics, allowing inspection or checkpoint resumption without exposing credentials.
