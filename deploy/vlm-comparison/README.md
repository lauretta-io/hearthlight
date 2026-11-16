# Five-second VLM video comparison

This comparison uses three supplied Drive recordings and four local models. The three additional models run in priority order,
followed by the existing Qwen2.5-VL-3B baseline. Each model receives the same five-second windows and
one frame per second. The final partial window uses its available frames.

The prompt comes from `shared/prompts/prompt_v2.yaml`. Its template and object
list are preserved. Its activity list is populated with the user's requested
focus terms, recklessness, driving, hurt, and taking items. Resolved prompts,
frame timestamps, and prompt hashes are recorded in `input-manifest.json`.

Inference uses BF16 weights, greedy decoding, a 1024-token response limit,
repetition penalty 1.1, and a 32-token repeated-ngram guard for all models.
MiniCPM uses its documented video settings of one image slice and 16x visual
downsampling. Model revisions and runtime versions are saved beside the raw
JSONL responses. Frames are prepared at a 960-pixel width. Each model applies
its own native image preprocessing afterward.

The runtime lives in `var/vlm-comparison/env`, inside the existing CUDA image.
It uses Transformers 5.7.0 with the image's existing PyTorch/CUDA installation.
`run_model.sh` pauses the Office logger to release GPU memory and restores it
when the model process exits. Completed windows are durable and skipped on a
restart. A model failure can be retried without discarding completed windows.

Run from the host after downloading the three source files into
`var/vlm-comparison/inputs`.

```sh
/home/lauretta/hearthlight/.venv/bin/python deploy/vlm-comparison/prepare.py
deploy/vlm-comparison/run_model.sh qwen3-vl-2b
deploy/vlm-comparison/run_model.sh minicpm-v-4.6
deploy/vlm-comparison/run_model.sh smolvlm2-2.2b
deploy/vlm-comparison/run_model.sh qwen2.5-vl-3b
python deploy/vlm-comparison/render.py --model qwen3-vl-2b
python deploy/vlm-comparison/render.py --model minicpm-v-4.6
python deploy/vlm-comparison/render.py --model smolvlm2-2.2b
python deploy/vlm-comparison/render.py --model qwen2.5-vl-3b
```

Each annotated MP4 preserves the source duration and audio, renders at 30 FPS,
and adds a black text panel above the complete source frame. The panel changes
at each five-second boundary. It identifies the model, the time range, activity
scores when supplied, detected activities, visible items, and the scene summary.
Incomplete JSON responses carry a format warning. A field is recovered only when its complete JSON value is present in the actual
response. Missing scores, summaries, and anomaly decisions are shown as unavailable.

The comparison measures observed model output and format behavior. The source
videos have no supplied ground-truth event labels. The model's reported anomaly
confidence is an uncalibrated estimate from the standard prompt.

## Qwen3 2B versus 4B evaluation (2026-11-12)

The paired evaluation is saved in `var/qwen3-evaluation-20261112`.
`protocol.json` freezes the original frame references and provisional visual
labels before inspecting benchmark responses. `protocol-v2.json` removes an
action word from the Japan actor locator; its labels and eligibility are
unchanged. All affected temporal cases were rerun for both models, with the
original responses retained in `temporal-v1.jsonl`.

- `run_qwen3_eval.sh` runs the unchanged Hearthlight standard prompt on all 42
  windows and the shuffled-frame action/order prompt on the 40 five-frame windows.
- `run_qwen3_repair.sh` performs the neutral-locator reruns and merges only the
  affected Japan cases into the final temporal results.
- `summarize_qwen3.py` checks prompt hashes, completeness and duplicates, then
  writes summary JSON, the metric table and per-class/per-case CSV evidence.
- `audit_qwen3.py` independently verifies event counts using sets, frame ordering
  using original source indices, action sets using bit masks, state changes and
  nearest-rank P95 using NumPy's inverse-CDF percentile.
- `present_qwen3.py` writes the readable text summary and comparison figure;
  `diagnose_qwen3_scores.py` adds machine-readable four-focus-score coverage.
- `render_qwen3_eval.py` annotates the three complete source videos per model.

GPU scripts serialize with the existing benchmark lock, pause the live logger,
and restore it on exit. The live model remains Qwen3-VL-2B-Instruct. Qwen3 4B is
retained in the comparison model cache. The retired Qwen2.5, SmolVLM2 and MiniCPM-V
checkpoint directories were deleted; their prior results and annotated videos
remain available. The older four-model benchmark requires re-downloading those
retired checkpoints if used again.

The accuracy labels are provisional assistant visual references, not independent
human annotations. Only driving has confirmed positive event examples in these
three clips. Schema-valid JSON is separate from supplying all requested scores.
See `benchmark-summary.txt`, `validation.json`, the frozen protocols and raw
responses for exact definitions, denominators, exclusions and caveats.

## Eight frames per ten seconds: 4B capacity probe

`var/qwen4b-8f-10s-20261112` contains this probe's frames, prompts, raw responses,
request timings and reports. It uses six camera-only windows from source video
`video-091517`, 4–64 seconds, with eight bin-centered samples per ten seconds at
640px width. Input sampling is 0.8 FPS per feed.

`run_qwen4b_8f.sh` measures six inherited-scoring requests, then replays two
synchronized logical feeds through the live scene/person prompt using YOLO/IoU
tracklets. The isolated test supplies null ReID IDs and excludes TransReID and
SigLIP. It does not write synthetic observations into production databases.
`run_qwen4b_8f_batch2.sh` measures a shared 4B model with batch size 2, using two
phase-offset copies of the same recording and the scoring prompt. Actual output
token counts exclude padding after EOS. The batch timer ends when both responses
are available.

`summarize_qwen4b_8f.py` checks counts, rate arithmetic, queue/deadline timestamps
and memory bounds, then exports `final-summary.json`, `benchmark-summary.txt` and
CSV tables. `plot_qwen4b_8f.py` creates the capacity chart. Mean processing time
and slowest time are reported; nearest-rank P95 equals the observed maximum in
these small samples. This is a short capacity probe, not a long-duration load or
behavior-accuracy test. Keep single-request timing separate from two-response
batch timing.

The live logger is restored on exit. These probes do not change its model,
camera configuration, frame sampling or output contract.
