# Episode animation effects

The approved animation set includes tummy wiggle, gentle jelly bounce, clap/step, penguin movement, floating balloons, glowing fireflies, ripple hops and bubbles. The existing wave, waist, step, sway and hop variants remain available. Scene lyrics select explicit actions; otherwise a repeatable four-scene dance phrase is used.

The original sky/foliage/grass motion, bounded camera zoom/pan, character approach/rest actions and story props remain. Landscape episodes and portrait Shorts use the same animation engine.

Smile/mouth deformation, head/ear warping and whole-sprite spinning remain disabled. A brief blink is permitted only on a conservative single eye-pair rig with opaque, low-texture surrounding skin; uncertain faces remain untouched. At least the upper 65% of each cropped actor (more for a lower detected face) is protected from body deformation. Balloons, fireflies and ripple hops retain their original sprite pixels before the optional blink/compositing.

Dancers share the requested musical beat phase across scenes; energy differences and half-beat ripple delays provide variation. Normal dance keeps the root on the floor, with alternating swing feet. Explicit hop/jelly moves alone lift the whole actor. Poses blend around a beat-aligned middle switch. This is CPU image deformation, not inferred anatomical joints or audio beat detection.

Camera pushes/pans ease in and out with cast bounds enforced. There is no hard mid-shot punch-in. Final assembly blends the outgoing held frame into each incoming shot over 160 ms while preserving five seconds per scene and the original audio timeline. Only two clips decode at once, and verified transition renders are cached.

Animation cache versions invalidate old rendered clips while preserving existing segmentation and background layers. These effects apply to new generation runs using the updated code; already uploaded videos and in-progress runs pinned to an older commit are unchanged.


## Purposeful travelling choreography

Spatial travel now requires a grounded scene intent. The leftmost friend approaches
the nearest waiting friend on the right to greet, join, help or share, stopping at
a safe gap. The waiting friend does not drift with the mover. Following uses a
spatial leader with delayed followers, preserving order. Ball-seeking routes aim
at the known ball overlay rendered by this engine and stop nearby.

Ordinary dance, generic walking without a destination, sleeping and ambiguous
non-character goals do not trigger whole-group travel. New verse visuals request
a visible target and reason; chorus phrases alternate gathering to start the
dance, local dancing and following a leader along the dance path. New image
prompts stage approaching friends a few steps apart, facing one another.

Roles use detected left/right cutout geometry, not inferred character names or
species. A single silhouette cannot approach an invisible friend; a cast already
close together is not pulled apart to manufacture travel. Very tight framing
limits follow routes. Camera bounds cover each moving or waiting actor.

Walking feet compensate body travel during stance, then advance during swing.
This remains cutout/mesh animation: no synthesized handover, object pickup,
anatomical 3D gait or lip-sync is claimed. The preview's first layout uses extra
starting separation for a clear approach example; production uses its generated
artwork's actual positions and available gap.
