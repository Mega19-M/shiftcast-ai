# Overlay cues `shiftcast-overlay-cues/1.0`
JSON: `{format, synthetic, match_id, cues:[{cue_id, type, start_min, end_min, text, event_ids, ...}]}`.
`type` ∈ `lower_third | stat_card | pitch_overlay`. `event_ids` always reference real source events. WebVTT export carries the same cue text.
This is an original illustrative format, not a broadcaster standard.
