# Likely judge questions
**Is it accurate on real football?** Unknown — synthetic data only; evaluation is same-author.
**Does it need AI keys?** No; local templates work offline. Azure is optional and untested live.
**How do you stop hallucinations?** Every story claim is re-checked in code against events; invented numbers/ids/names fail; failures trigger a local fallback.
**Is "strength" a probability?** No — a documented heuristic from the p-value.
**Do you claim causation?** No; edges are temporal, statistical or recorded.
**Why 0.53 precision?** Hand-set thresholds, uncorrected multiple windows; flank_overload is noisy.
**Are these real teams?** No, fictional.
