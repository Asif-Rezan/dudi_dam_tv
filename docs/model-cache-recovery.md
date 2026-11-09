# Verified model-download and cache recovery — 2026-11-09

Run [42571467173](https://github.com/Asif-Rezan/dudi_dam_tv/actions/runs/42571467173)
completed lyrics, long music, Shorts music and portrait artwork. Seven landscape
animation workers failed. The inspected `images (11)` job `129021633668` failed
while rembg downloaded BiRefNet with HTTP 504. Its unguarded LaMa download path
has the same failure mode as the other destination project.

Ported the model-download/cache fix from `youtube-dark-psychology-automation`
at `e7e95a9`, retaining this project's own public packaging and account wiring:

- Four bounded download attempts alternate official release and asset API URLs.
- Temporary downloads are published atomically after exact size/checksum checks.
- BiRefNet retains rembg's published MD5. LaMa uses the SHA-256 verified from the
  publisher's actual v0.1.0 release asset, not an alternative model.
- Production prepares shared caches before inference; landscape/portrait workers,
  lyrics and manual Shorts restore their own model families. Caches are saved
  before generation so later rendering failures do not discard the weights.
- Cache keys use exact model revisions/checksums, without run IDs, shard numbers
  or broad fallback prefixes. Only public `.models/` directories are cached.
- Matching image shards and Shorts audio can be restored from `prepared_run`;
  manifest/hash checks reuse completed assets and regenerate invalid/missing work.
- Existing pinned llama-cpp-python source fallback, bounded runner package setup,
  audio repairs, generation duration and scheduling are retained.

## Owner-approved 10 GB policy

Keep the existing 10 GB repository cache quota. Persist SSD-1B (6.54 GiB), Qwen
(2.28 GiB) and BiRefNet/LaMa (0.33 GiB): approximately 9.15 GiB in total. The
4.605 GiB ACE-Step archive is deliberately not persisted because it would evict
the models shared by many image workers. Music weights download when needed and
reuse runner-local files between segments. Competing pip caches are disabled.
Cache entries are repository-scoped: this repository warms its own copies.
GitHub can expire caches after inactivity; verified cache-miss download remains
available. No paid cache capacity or billing settings are enabled.

## Preservation, validation and rollback

Baseline `5184848`, rollback tag `before-model-cache-2026-11-09`. Restore on a new
branch using `git restore --source before-model-cache-2026-11-09 -- .` and commit
the restoration, without rewriting history. Cloud settings/caches are separate.

191 component tests pass, including 504 retry, corrupt/partial-file rejection,
cache key invalidation and saved-stage recovery. Actionlint and git diff checks
pass. Twenty metadata, thumbnail, publication/account files and reference assets
were compared byte-for-byte with the baseline. Thumbnail creation remains
independent of the opening scene. The model warmup workflow checks actual
BiRefNet segmentation and LaMa CPU inference without publishing a video.

To resume the failed episode on corrected code, use original run ID
`dudi-reference-20261109-01` with `prepared_run=42571467173`.

## Primary sources

- [rembg BiRefNet downloader and checksum](https://github.com/danielgatis/rembg/blob/v2.0.67/rembg/sessions/birefnet_general_lite.py)
- [LaMa publisher's release](https://github.com/enesmsahin/simple-lama-inpainting/releases/tag/v0.1.0)
- [GitHub cache restore/save and capacity behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
- [Hugging Face model-cache behavior](https://huggingface.co/docs/huggingface_hub/main/guides/download)
