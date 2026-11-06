from datetime import datetime


def eligible_feature(data, feature_id, decision_at):
    if decision_at.tzinfo is None or decision_at.utcoffset().total_seconds() != 0:
        raise ValueError("UTC_REQUIRED")
    eligible,excluded = [],[]
    for f in data.features:
        if f.feature_id != feature_id:
            continue
        if max(f.event_time,f.effective_time,f.published_at,f.available_at,f.ingested_at) > decision_at:
            excluded.append({"source_revision":f.source_revision,"reason":"NOT_AVAILABLE_AT_DECISION"})
        else:
            eligible.append(f)
    eligible.sort(key=lambda f:max(f.published_at,f.available_at,f.ingested_at))
    if len(eligible)>1:
        a,b = eligible[-2:]
        if max(a.published_at,a.available_at,a.ingested_at) == max(b.published_at,b.available_at,b.ingested_at):
            raise ValueError("AMBIGUOUS_REVISION")
    return (eligible[-1] if eligible else None),excluded
