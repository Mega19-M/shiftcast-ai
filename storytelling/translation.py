"""English and Tamil sentence templates.

Translation strategy (honest version): every sentence the app writes itself comes
from a template that exists in BOTH languages and receives the SAME variables
(team names, player names, numbers, event ids, scores). Names and numbers are
inserted unchanged, so they cannot be altered by translation. For any other
text (e.g. produced by a language model) ``preserved()`` in
``claim_checker`` checks that all numbers, ids and names survive.

The Tamil templates were written by the project author's assistant, not by a
professional translator: please have a native Tamil speaker review them before
a public demo.
"""
from __future__ import annotations

LANGUAGES = {"en": "English", "ta": "தமிழ் (Tamil)"}

LANE_WORD = {
    "en": {"left": "left", "right": "right", "center": "central"},
    "ta": {"left": "இடது", "right": "வலது", "center": "மைய"},
}
PERIOD_WORD = {
    "en": {"first_half": "first half", "second_half": "second half", "full": "full match"},
    "ta": {"first_half": "முதல் பாதி", "second_half": "இரண்டாம் பாதி", "full": "முழு ஆட்டம்"},
}

T: dict[str, dict[str, str]] = {
    "en": {
        # --- analytical headlines (carry the statistic) -------------------
        "hl_turnover_spike": "From {s}' to {e}', {team} had {n} turnovers, against about {exp} expected from their rate in the rest of the match (p = {p}).",
        "hl_shot_surge": "{team} took {n} shots between {s}' and {e}', against about {exp} expected from their rate in the rest of the match (p = {p}).",
        "hl_defensive_cluster": "{team} lost the ball {n} times in their own defensive third between {s}' and {e}', against about {exp} expected (p = {p}).",
        "hl_flank_overload": "{share} of the {tot} attacking-third passes and shots by {team} between {s}' and {e}' went down the {lane} flank, against a baseline of {base} (p = {p}).",
        "hl_possession_shift": "{team} were involved in {share} of all events between {s}' and {e}', against a baseline of {base} (p = {p}).",
        # --- plain fan wording -----------------------------------------------
        "fan_turnover_spike": "{team} kept giving the ball away between {s}' and {e}': {n} turnovers in total.",
        "fan_shot_surge": "{team} threw everything forward between {s}' and {e}' with {n} shots.",
        "fan_defensive_cluster": "{team} struggled to play out from the back between {s}' and {e}', losing the ball {n} times near their own goal.",
        "fan_flank_overload": "{team} kept attacking down the {lane} side between {s}' and {e}' - {share} of their attacks in the final third.",
        "fan_possession_shift": "{team} took over the game between {s}' and {e}', involved in {share} of the action.",
        # --- broadcast lines -----------------------------------------------------
        "bc_turnover_spike": "From {s}' to {e}': {n} turnovers for {team}. Something may be forcing errors here.",
        "bc_shot_surge": "From {s}' to {e}', {team} fire in {n} shots. The pressure is on and it may tell.",
        "bc_defensive_cluster": "From {s}' to {e}', {team} keep losing it in their own third, {n} times. Dangerous territory.",
        "bc_flank_overload": "From {s}' to {e}', {team} keep going down the {lane} flank, {share} of their final-third play. The opposition may see it coming.",
        "bc_possession_shift": "From {s}' to {e}', {team} are involved in {share} of the action. The momentum may be shifting.",
        # --- interpretation (always hedged) --------------------------------------
        "interp_turnover_spike": "This may point to {team} being pressed or forced into risky passes, but event data alone cannot show the reason.",
        "interp_shot_surge": "This suggests a spell of sustained attacking pressure by {team}, though the data does not show shot quality.",
        "interp_defensive_cluster": "This could indicate difficulty playing out from the back under pressure; the data does not show who was pressing.",
        "interp_flank_overload": "This suggests a deliberate focus on the {lane} flank by {team}, although event data cannot confirm tactical intent.",
        "interp_possession_shift": "This suggests the balance of play moved towards or away from {team}, but event share is not true possession time.",
        # --- shared sentences --------------------------------------------------------
        "score": "At {m}', the score was {home} {a}-{b} {away}.",
        "score_ft": "The score at the end of the data was {home} {a}-{b} {away}.",
        "goal": "{player} scored for {team} at {clock} ({event_id}).",
        "hyp": "Heuristic scenario {letter} (hypothetical): {metric} could range from {low} to {high} instead of the measured {actual} - an assumption-based estimate, not a prediction.",
        "caveat": "Caveat: this is an association in synthetic event data, not proof of cause.",
        "evidence_line": "Supporting events: {ids}.",
        "strength_line": "Heuristic evidence strength {strength} (= min(1, -log10 p / 6)); it is not a probability.",
        "rule_line": "Detection rule: {rule}",
        # --- recap ---------------------------------------------------------------------
        "rc_score": "Score {period}: {home} {a}-{b} {away}.",
        "rc_stats": "{team} had {shots} shots and {turnovers} turnovers in the {period}.",
        "rc_none": "No key moments were detected in the {period}.",
        "rc_moment": "Key moment: {title}.",
    },
    "ta": {
        "hl_turnover_spike": "{s}' முதல் {e}' வரை {team} அணி {n} முறை பந்தை இழந்தது; ஆட்டத்தின் மற்ற பகுதியின் விகிதத்தின்படி எதிர்பார்க்கப்பட்டது சுமார் {exp} (p = {p}).",
        "hl_shot_surge": "{s}' முதல் {e}' வரை {team} அணி {n} ஷாட்கள் அடித்தது; மற்ற பகுதியின் விகிதத்தின்படி எதிர்பார்க்கப்பட்டது சுமார் {exp} (p = {p}).",
        "hl_defensive_cluster": "{s}' முதல் {e}' வரை சொந்த தடுப்புப் பகுதியில் {team} அணி {n} முறை பந்தை இழந்தது; எதிர்பார்க்கப்பட்டது சுமார் {exp} (p = {p}).",
        "hl_flank_overload": "{s}' முதல் {e}' வரை {team} அணியின் {tot} இறுதிப் பகுதி பாஸ்/ஷாட்களில் {share} {lane} பக்கவாட்டில் சென்றன; வழக்கமான அளவு {base} (p = {p}).",
        "hl_possession_shift": "{s}' முதல் {e}' வரை மொத்த நிகழ்வுகளில் {share} {team} அணியினுடையவை; வழக்கமான அளவு {base} (p = {p}).",
        "fan_turnover_spike": "{s}' முதல் {e}' வரை {team} அணி மீண்டும் மீண்டும் பந்தை இழந்தது: மொத்தம் {n} முறை.",
        "fan_shot_surge": "{s}' முதல் {e}' வரை {team} அணி முழு வேகத்தில் தாக்கி {n} ஷாட்கள் அடித்தது.",
        "fan_defensive_cluster": "{s}' முதல் {e}' வரை {team} அணி பின்னிலிருந்து பந்தை எடுத்துச் செல்லத் திணறி, சொந்த கோல் அருகே {n} முறை பந்தை இழந்தது.",
        "fan_flank_overload": "{s}' முதல் {e}' வரை {team} அணி {lane} பக்கத்தில் தொடர்ந்து தாக்கியது - இறுதிப் பகுதி தாக்குதல்களில் {share}.",
        "fan_possession_shift": "{s}' முதல் {e}' வரை {team} அணி ஆட்டத்தைக் கைப்பற்றியது; நிகழ்வுகளில் {share} அவர்களுடையவை.",
        "bc_turnover_spike": "{s}' முதல் {e}' வரை: {team} அணிக்கு {n} பந்து இழப்புகள். ஏதோ ஒன்று தவறுகளை உருவாக்கியிருக்கலாம்.",
        "bc_shot_surge": "{s}' முதல் {e}' வரை {team} அணி {n} ஷாட்கள் அடித்துள்ளது. அழுத்தம் தொடர்கிறது, அது பலன் தரலாம்.",
        "bc_defensive_cluster": "{s}' முதல் {e}' வரை {team} அணி சொந்தப் பகுதியில் {n} முறை பந்தை இழந்தது. ஆபத்தான பகுதி.",
        "bc_flank_overload": "{s}' முதல் {e}' வரை {team} அணி {lane} பக்கவாட்டில் தொடர்ந்து தாக்குகிறது, இறுதிப் பகுதி ஆட்டத்தில் {share}. எதிரணி இதை எதிர்பார்த்திருக்கலாம்.",
        "bc_possession_shift": "{s}' முதல் {e}' வரை ஆட்டத்தில் {share} {team} அணியினுடையது. ஆட்டத்தின் போக்கு மாறக்கூடும்.",
        "interp_turnover_spike": "{team} அணி அழுத்தத்தில் இருந்திருக்கலாம் அல்லது ஆபத்தான பாஸ்களுக்குத் தள்ளப்பட்டிருக்கலாம்; ஆனால் நிகழ்வுத் தரவு மட்டும் காரணத்தைக் காட்டாது.",
        "interp_shot_surge": "{team} அணி தொடர்ச்சியான தாக்குதல் அழுத்தம் கொடுத்திருக்கலாம்; ஆனால் ஷாட்டின் தரம் தரவில் இல்லை.",
        "interp_defensive_cluster": "அழுத்தத்தின் கீழ் பின்னிலிருந்து ஆட்டத்தை உருவாக்குவதில் சிரமம் இருந்திருக்கலாம்; யார் அழுத்தினார்கள் என்பதைத் தரவு காட்டாது.",
        "interp_flank_overload": "{team} அணி {lane} பக்கவாட்டில் வேண்டுமென்றே கவனம் செலுத்தியிருக்கலாம்; ஆனால் உத்தி நோக்கத்தை நிகழ்வுத் தரவு உறுதிப்படுத்தாது.",
        "interp_possession_shift": "ஆட்டத்தின் சமநிலை {team} அணியின் பக்கமாக அல்லது எதிராக மாறியிருக்கலாம்; ஆனால் நிகழ்வுப் பங்கு என்பது உண்மையான பந்துக் கட்டுப்பாட்டு நேரம் அல்ல.",
        "score": "{m}' நிமிடத்தில் ஸ்கோர் {home} {a}-{b} {away}.",
        "score_ft": "தரவின் இறுதியில் ஸ்கோர் {home} {a}-{b} {away}.",
        "goal": "{clock} நிமிடத்தில் {player} ({team}) கோல் அடித்தார் ({event_id}).",
        "hyp": "அனுமான சூழல் {letter}: {metric} அளவீடு {actual} என்பதற்கு பதிலாக {low} முதல் {high} வரை இருக்கலாம் - இது அனுமான மதிப்பீடு, கணிப்பு அல்ல.",
        "caveat": "எச்சரிக்கை: இது செயற்கை நிகழ்வுத் தரவில் காணப்படும் தொடர்பு மட்டுமே; காரணத்திற்கான சான்று அல்ல.",
        "evidence_line": "ஆதார நிகழ்வுகள்: {ids}.",
        "strength_line": "அனுமான சான்று வலிமை {strength} (= min(1, -log10 p / 6)); இது நிகழ்தகவு அல்ல.",
        "rule_line": "கண்டறிதல் விதி: {rule}",
        "rc_score": "{period} ஸ்கோர்: {home} {a}-{b} {away}.",
        "rc_stats": "{period}: {team} அணி {shots} ஷாட்களும் {turnovers} பந்து இழப்புகளும் பதிவு செய்தது.",
        "rc_none": "{period}: முக்கிய தருணங்கள் எதுவும் கண்டறியப்படவில்லை.",
        "rc_moment": "முக்கிய தருணம்: {title}.",
    },
}


def tr(lang: str, key: str, **kw) -> str:
    """Render a template. Falls back to English if the language or key is missing."""
    table = T.get(lang) or T["en"]
    tpl = table.get(key) or T["en"][key]
    return tpl.format(**kw)


def lane_word(lang: str, lane: str) -> str:
    return LANE_WORD.get(lang, LANE_WORD["en"]).get(lane, lane)


def period_word(lang: str, period: str) -> str:
    return PERIOD_WORD.get(lang, PERIOD_WORD["en"])[period]
