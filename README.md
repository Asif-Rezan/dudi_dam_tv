# Heart and Mind — Hindi Music Automation

All AI inference and video rendering run on standard **GitHub Actions CPU runners**. There is no hosted Hugging Face Space, ZeroGPU call, Groq key, remote music API, GPU rental, or self-hosted runner requirement. Public model weights are downloaded anonymously; downloads do not perform remote inference.

## Workflow

The generation flow is restored from successful run **#14**, commit `dba31ba`. Music synthesis, image generation, rendering settings and model revisions match that run. There is no lyric-transcription job, five-second storyboard or image-shard matrix. The music and images jobs run in parallel. Run #14 completed in 46m 10s; that is a measured example, not a guaranteed duration.

1. **Lyrics job:** original Hindi Devanagari lyrics and metadata using the same pinned Qwen3-4B CPU model as [Rezan After Dark](https://github.com/Asif-Rezan/Rezan-After-Dark).
2. **Music job:** ACE-Step 1.5 `acestep-v15-turbo` runs directly on the GitHub CPU. Hindi vocals, one complete 180–360 second song, eight diffusion steps. Optional ACE-Step planning LM is disabled because lyrics and the musical prompt are already supplied.
3. **Images job (alongside music):** the reference project’s pinned `segmind/SSD-1B` diffusion model generates two fresh song-specific images on CPU: a cinematic background and a separate expressive thumbnail scene. Qwen writes both visual prompts from the song’s story; seeds differ by lyrics and image purpose.
4. **Publish job:** measure the real audio duration, render a 1920×1080 branded waveform video and thumbnail, back up privately to Drive, upload publicly to the exact Heart & Mind channel, and verify actual public visibility and HD processing.

Songs are never looped or padded to meet the duration requirement. Artwork is generated anew for each song, never selected from a shared image library. Romantic and separation thumbnails feature beautiful South Asian adult couples aged 25–35, with distinct expressive faces and a clear emotional moment. Healing songs may feature one hopeful young adult female lead. Both generated sources are text-free: Hindi, Romanized Hindi and English lettering are suppressed, and no title, badge or logo is added to the thumbnail. The video uses its own colorful generated scene with a low-positioned waveform.

Lyrics run first; music and images then run on separate CPU workers; publishing waits for both. Only publishing and cleanup receive Google credentials. The image job has a 120-minute deadline and 12 GB swap. It uses public weights without an image inference API or extra secret. Image failures stop publishing rather than substitute the old channel-name graphic. Music inference has a 350-minute deadline, a CPU-only PyTorch installation, and 16 GB of additional swap. CPU generation can be slow; successful completion still depends on the runner's memory, disk and time limits. A failed run is not reported as published.

## Songwriting and packaging

Eight daily directions rotate across acoustic romance, piano heartbreak, indie dream pop, uplifting folk, celebratory dance pop, contemporary ghazal-inspired ballads, cinematic soul and monsoon lo-fi. Each direction changes the story, arrangement and vocal delivery. Lyrics ask for concrete scenes, singable phrasing, a consistent chorus and a developing emotional arc. Rotation uses the Dhaka calendar date, so it also works in the isolated lyrics job without Drive access.

Songwriting and packaging use separate Qwen completions to keep each response manageable. Validated lyrics are checkpointed in `song-draft.json` before packaging; the `prepared_run` restore also supports the `music-input` artifact from a failed lyrics job. Retry logs identify the schema field, failed constraint and output token count without exposing generated text.

New `song.json` files carry `tags`, `thumbnail_text`, `visual_mood`, `background_prompt` and `thumbnail_prompt`. Title prompts prioritize the original Hindi/Romanized song name plus a truthful, mood-specific search phrase and the release year. Description prompts lead with the song name and relevant Hindi/English search terms, then its specific story and listening context. The publisher removes internal tool/model credits and unverified creator attributions, adds only the channel credit, and limits public hashtags to three. Thumbnail prompts request close chest-up compositions with distinct, clearly lit faces, natural skin and a softly blurred lyric-specific setting. Background prompts use a wider environmental view, recognizable people on the right-center, scenic depth and a clear lower edge for the existing waveform. The image worker refuses text-enabled inference; the saved thumbnail_text field remains only for backwards-compatible metadata and the existing video overlay. SSD-1B is not relied on for Hindi typography. Text-free prompts, text-suppression negatives and removal of the old poster/title instructions address the malformed-lettering problem. Generated images still need visual review for anatomy, unwanted incidental markings and story relevance. Uploads use the generated tags, deduplicate them and enforce a conservative YouTube character budget. Packaging avoids invented famous-artist associations and popularity claims. These changes improve relevance and readability; CTR and search performance require real audience data to evaluate.

SSD-1B uses revision `60987f37e94cd59c36b1cba832b9f97b57395a10`, matching Rezan After Dark. It generates 1024×576 sources at 20 steps in Actions, which are composed into 1920×1080 video artwork and a 1280×720 thumbnail. The model’s output safety handling stays enabled, with bounded retries and no blank-image fallback. Seeds, prompts, dimensions, steps and model revision are recorded in `image-manifest.json`. Cached images are reused only for the same song and generation settings, including the visual-style version, negative prompt and guidance scale. Old lettered-poster manifests are invalidated automatically. Two images take additional CPU time; quality and timing need live verification on the runner.

For local image preparation, install CPU PyTorch and `requirements-images-cpu.txt` alongside `requirements.txt`, then run `python prepare_music.py --run-id YOUR_RUN_ID --stage images` after lyrics preparation. The publishing renderer requires both generated source images. Font: bundled Oswald under the SIL Open Font License in `assets/artwork/FONT-LICENSE.txt`.

## Drive cleanup after successful publication

The main workflow shows a separate **Clean published media from Drive** job after **publish**. Publishing defers deletion to that job; local pipeline runs still clean up by default. After the upload is freshly verified as public, processed in HD, on the expected channel, with matching title, description and tags and a confirmed thumbnail upload, temporary media for that exact song is permanently deleted from the dedicated private Drive folder. This follows the reference project's exact-ID cleanup journal approach. It removes `song.wav`, `video.mp4`, `thumbnail.jpg` and generated source images; it retains `song.json`, publishing state, history, image-generation settings and the cleanup journal. Unrelated files and other runs are untouched. Failed or incomplete uploads retain their media.

Cleanup checks each target's exact filename, hashed workflow key, parent folder, owner-only permissions and non-folder type before deletion. It saves a durable manifest before deleting anything and checkpoints progress after each file. Rerunning an already published song resumes cleanup without generating or uploading another video.

The **Clean published song media from Drive** workflow also runs after a successful publishing workflow, including a generation that started before the cleanup code was added. It reads the completed song identity from that run's JSON artifact and uses trusted default-branch code to verify YouTube again. For cleanup-only recovery, manually run this workflow with the exact `run_id`; no song generation or video upload occurs.

## Start or resume

Open GitHub Actions → **Hindi album music generation and public publishing** → **Run workflow**.

- `run_id`: stable song identifier, e.g. `first-hindi-song-20261025`.
- `prepared_run`: optional numeric previous GitHub run ID with a `generated-music-<ID>` artifact. Reuse the same `run_id` to restore its lyrics and any completed audio. When available, the separate `generated-artwork-<ID>` artifact restores completed image work too; older runs without it generate fresh scenes from their saved song.

Old checkpoints from the removed hosted backend can supply the lyrics. The CPU worker does not resubmit their remote tasks. A failed local music process can restart with the saved lyrics. Completed audio is reused. An interrupted YouTube upload without a saved video ID still requires reconciliation to prevent duplicate publishing.

The scheduled workflow is enabled daily at **03:00 Asia/Dhaka (3:00 AM Bangladesh time)**, gated by repository variable `AUTOMATION_ENABLED=true`. Set that variable to `false` to pause scheduling. Manual runs request public publishing.

## Google accounts and secrets

| Purpose | Account |
| --- | --- |
| Heart & Mind YouTube | asifrezan@gmail.com |
| Google Cloud owner | asifrezan.office@gmail.com |
| Private Drive media | asifrezanit@gmail.com |

The previously unused project in organization `931428574736` is named **Heart and Mind**, project ID `project-5a0943f4-af8e-49e0-8e4`, number `563533070055`. Before reuse, credentials were empty, API traffic had no data for 30 days, and asset inventory contained only default project/services/logging resources.

The OAuth app is **In production**, with YouTube Data API v3 and Drive API enabled. Fresh offline credentials were verified for channel `UCDTjTh7ORO2J_5OrR0dESTQ` and its private project-marked Drive folder. Required encrypted repository Actions secrets:

- `YOUTUBE_TOKEN_JSON`
- `EXPECTED_CHANNEL_ID`
- `DRIVE_TOKEN_JSON`
- `DRIVE_FOLDER_ID`

No Hugging Face or Groq token is needed. Production removes the Testing-specific seven-day refresh-token limit; revocation and other expiry conditions can still require reauthorization.

For future account setup, download the dedicated Desktop client JSON as ignored `client_secrets.json`, install `requirements.txt`, then run `python setup_accounts.py youtube --channel-id UCDTjTh7ORO2J_5OrR0dESTQ` and `python setup_accounts.py drive`. The helper uses GitHub CLI if available; otherwise it prepares inputs under ignored owner-only `.credentials/` for encrypted Actions secrets. Never commit or print credentials.

## Pinned music runtime

- Official source: `ace-step/ACE-Step-1.5`, commit `ca1e85fe9430179831e6bc6be790c332190a3866`.
- Public weights: `ACE-Step/Ace-Step1.5`, revision `19671f406d603126926c1b7e2adc169acbcade22`.
- Downloaded components: turbo DiT, official VAE, Qwen3 embedding encoder. No optional 5Hz planning LM is downloaded or loaded.
- `requirements-music-cpu.txt` contains the inference dependencies. PyTorch and torchaudio CPU wheels are installed from PyTorch's official CPU index.

The wrapper checks the source commit before importing it and initializes with `device='cpu'`, no FlashAttention, no GPU backend, no compilation and no hosted fallback. It follows the official [CPU-only installation](https://github.com/ace-step/ACE-Step-1.5/blob/ca1e85fe9430179831e6bc6be790c332190a3866/docs/en/INSTALL.md#cpu-only-mode) and [inference API](https://github.com/ace-step/ACE-Step-1.5/blob/ca1e85fe9430179831e6bc6be790c332190a3866/docs/en/INFERENCE.md).

## Checks

`python -m unittest -v` exercises duration and Hindi validation, the pinned anonymous downloads, CPU-only generation parameters, safe local retries, rejection of private-only upload results, per-song image seeds, image checkpoint recovery, safety rejection handling, style rotation and metadata budgets. A live Actions run additionally imports the real pinned ACE-Step runtime before downloading its model weights and generating audio. Unit tests alone do not establish actual song quality or completed publication.

CPU synthesis configures the native `ACESTEP_GENERATION_TIMEOUT` to 18,000 seconds before importing ACE-Step (its default is only 600 seconds). Startup verifies the actual imported native timeout. The child worker has a separate 18,900-second hard deadline, within the 350-minute music job. A one-minute heartbeat reports elapsed CPU time and peak memory while synthesis runs. These are limits, not completion-time promises.

New songs alternate solo male/female vocal directions by Asia/Dhaka calendar date: October 28, 2026 is male, October 29 female, then repeat. Lyrics and the Hindi editing pass follow that narrator. Saved song checkpoints retain their original voice across retries; existing audio is not changed. Vocal gender is guided through the music caption, so generated audio still needs listening review.

Manual workflow dispatch can select `vocal_gender=male` or `female` for a new song; `auto` remains the default for scheduled runs. This one-off choice does not shift the daily calendar rotation. Use a new run ID when choosing a different voice; saved songs cannot be relabeled.

## Text-free visual refresh

The production style is `heart-mind-textfree-cinematic-v2`. Cast and camera instructions lead the short prompts so SSD-1B does not lose them behind scenery or typography instructions. Romance uses tender eye contact; heartbreak shows the couple apart rather than an unrelated older male stock portrait; healing uses hopeful expression. The thumbnail and video background remain distinct scenes with different song-derived seeds. Safety checks remain enabled.

Run the **Demo thumbnail and background preview** workflow with `source_run` empty to generate new review-only images using the actual production model. This workflow does not synthesize a song, upload a YouTube video or change published thumbnails. Recomposition from an old `source_run` does not regenerate its existing pixels; use a fresh preview to assess this style. Better CTR is a design aim, not a measured result; use real impressions/click-through data and compare comparable releases.
