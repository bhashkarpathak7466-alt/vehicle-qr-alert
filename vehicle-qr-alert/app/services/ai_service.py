"""
AI-based risk scoring service, with graceful degradation.

Plain-language summary of the design decision:

  When someone reports an alert (e.g. "car window is smashed and
  someone is inside"), we want to score how urgent it is so the
  owner sees critical alerts first.

  Ideally, this call goes to a real LLM API (e.g. Anthropic's API)
  to read the free text and judge severity with real understanding
  of context and nuance.

  BUT: in production, external AI APIs can be slow, rate-limited,
  temporarily down, or simply not configured (e.g. no API key set
  in this environment). If the whole alert-reporting feature broke
  every time the AI call failed, that would be a serious reliability
  problem for something that might be safety-critical.

  So this service implements "graceful degradation":
    1. Try the AI path first, if AI_ENABLED and a key is configured.
    2. If that fails (exception, timeout, missing key) OR AI is
       disabled, fall back to a deterministic rule-based keyword
       matcher instead. It's less nuanced, but it's fast, free,
       and never crashes the request.
    3. The response always tells the caller which path was used
       (source: "ai" or "rule_based"), so nothing is hidden.

  In this project, AI is disabled by default and the rule-based
  path is what actually runs -- which is an honest, resume-ready way
  to demo "AI-powered risk scoring" without needing a paid API key.
"""

from dataclasses import dataclass
import logging

from app.core.config import settings

logger = logging.getLogger("ai_service")

# Keyword -> weight. Higher weight = more severe.
_KEYWORD_WEIGHTS: dict[str, float] = {
    "fire": 1.0,
    "smoke": 0.9,
    "explode": 1.0,
    "break in": 0.9,
    "break-in": 0.9,
    "broken window": 0.8,
    "smashed": 0.8,
    "stolen": 0.9,
    "theft": 0.9,
    "leaking fuel": 0.85,
    "leaking gas": 0.85,
    "child": 0.95,
    "trapped": 0.9,
    "accident": 0.7,
    "collision": 0.7,
    "blocking": 0.3,
    "parked wrong": 0.2,
    "flat tire": 0.25,
    "lights on": 0.15,
    "alarm going off": 0.5,
    "suspicious": 0.5,
}


@dataclass
class RiskResult:
    score: float          # 0.0 - 1.0
    label: str            # low / medium / high / critical
    matched_keywords: list[str]
    source: str            # "ai" or "rule_based"


def _label_for_score(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def _rule_based_score(message: str) -> RiskResult:
    text = message.lower()
    matched = []
    max_weight = 0.0
    for keyword, weight in _KEYWORD_WEIGHTS.items():
        if keyword in text:
            matched.append(keyword)
            max_weight = max(max_weight, weight)

    # Baseline score for any report at all, even with no keyword hits,
    # so alerts aren't scored as literally zero risk.
    score = max_weight if matched else 0.1
    return RiskResult(
        score=round(score, 2),
        label=_label_for_score(score),
        matched_keywords=matched,
        source="rule_based",
    )


def _ai_score(message: str) -> RiskResult | None:
    """
    Placeholder for a real AI call (e.g. Anthropic Messages API).
    Returns None on any failure so the caller falls back gracefully.
    Not invoked at all unless AI_ENABLED=true and AI_API_KEY is set.
    """
    if not settings.AI_ENABLED or not settings.AI_API_KEY:
        return None
    try:
        # Real implementation would call the AI API here, e.g.:
        #
        # response = anthropic_client.messages.create(
        #     model="claude-sonnet-4-6",
        #     max_tokens=200,
        #     messages=[{"role": "user", "content": f"Rate urgency 0-1 of: {message}"}],
        # )
        # ... parse response into RiskResult(source="ai", ...)
        #
        # Intentionally not called in this environment (no network
        # access to external AI APIs from this sandbox, and no key
        # configured) -- this is exactly the kind of "heavy-duty,
        # can't run for real here" component mocked per your request.
        raise NotImplementedError("AI call not wired up in this environment")
    except Exception:
        return None


def score_alert(message: str) -> RiskResult:
    """
    Public entrypoint: tries AI first, falls back to rule-based.
    This function is what routers/services call -- callers never
    need to know which path actually ran.
    """
    ai_result = _ai_score(message)
    if ai_result is not None:
        return ai_result
    return _rule_based_score(message)


# ----------------------------------------------------------------
# Authenticity / fraud check
#
# Plain-language summary of the design decision:
#
#   Anyone can scan a QR sticker and submit a report -- no login,
#   by design, so a genuine passerby can act fast. That openness
#   also means someone could submit a prank or spam report.
#
#   Ideally, this call goes to a vision-capable AI model: read the
#   message AND look at the attached photo, and judge whether they
#   genuinely match ("smashed window" + a photo that actually shows
#   a smashed window) versus a mismatch or an empty joke report.
#
#   Same graceful-degradation pattern as risk scoring: if AI isn't
#   configured, fall back to a transparent, rule-based heuristic
#   instead of blocking the report or crashing.
# ----------------------------------------------------------------

_PRANK_PHRASES = ["just kidding", "jk", "lol", "haha", "prank", "test test", "asdf", "idk lol", "ignore this"]

_SERIOUS_ISSUE_TYPES = {"Emergency / Accident", "Suspicious Activity / Theft"}


@dataclass
class AuthenticityResult:
    label: str    # "likely_genuine" / "needs_review" / "likely_prank"
    reason: str   # short, human-readable explanation -- always shown, never hidden
    source: str   # "ai" or "rule_based"


def _rule_based_authenticity(message: str, issue_type: str, has_image: bool) -> AuthenticityResult:
    text = message.strip().lower()

    if len(text) < 6:
        return AuthenticityResult(
            "likely_prank",
            "Message is too short to describe a real issue.",
            "rule_based",
        )

    if any(phrase in text for phrase in _PRANK_PHRASES):
        return AuthenticityResult(
            "likely_prank",
            "Message contains language typical of a joke or test report.",
            "rule_based",
        )

    if issue_type in _SERIOUS_ISSUE_TYPES and not has_image and len(text) < 25:
        return AuthenticityResult(
            "needs_review",
            f"'{issue_type}' is a serious category, but the report has a short description and no photo -- worth a manual check.",
            "rule_based",
        )

    # IMPORTANT (bug fix): this rule-based path has no way to look at
    # the actual pixels in an attached photo. It used to return
    # "likely_genuine" just because a photo was attached and the text
    # was long enough -- but "a photo exists" is not the same as "the
    # photo shows what the reporter described." That let completely
    # unrelated images (a selfie, a building, anything) sail through
    # as "genuine" whenever AI wasn't actually running.
    #
    # The only component that can genuinely verify a photo is the
    # real vision-AI call (_ai_authenticity_check). So this fallback
    # is honest about its limits: it never claims "likely_genuine" on
    # its own -- it always defers to manual review when a photo is
    # involved and AI isn't available to check it.
    if has_image:
        return AuthenticityResult(
            "needs_review",
            "A photo was attached, but AI is not enabled/available to verify it actually matches the "
            "description -- this rule-based fallback cannot inspect image content. Flagged for manual review.",
            "rule_based",
        )

    return AuthenticityResult(
        "needs_review",
        "No photo attached and no AI configured to verify further -- treated as unverified until the owner checks.",
        "rule_based",
    )


def _anthropic_authenticity_check(
    message: str,
    issue_type: str,
    image_bytes: bytes | None = None,
    image_media_type: str | None = None,
) -> AuthenticityResult | None:
    """
    Real vision-capable AI call via Claude (Anthropic). Requires
    AI_ENABLED=true, AI_PROVIDER="anthropic", a valid AI_API_KEY, AND
    billing credits on the Anthropic console (this is a paid API --
    a valid key alone is not enough if the account has $0 balance).

    Returns None on ANY failure so the caller always falls back
    gracefully to the rule-based path.
    """
    if not settings.AI_ENABLED or not settings.AI_API_KEY:
        return None

    try:
        import base64
        import json as _json
        import anthropic

        client = anthropic.Anthropic(api_key=settings.AI_API_KEY)

        prompt = _authenticity_prompt(message, issue_type)

        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_bytes and image_media_type:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": base64.b64encode(image_bytes).decode(),
                },
            })

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": content}],
        )

        raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return _parse_authenticity_response(raw_text)

    except Exception as exc:
        # Covers: anthropic package not installed, no network access,
        # API error (including "insufficient credits"), malformed/
        # non-JSON response, timeout -- the request still falls back
        # to the rule-based path rather than failing, but we LOG the
        # real reason instead of hiding it.
        logger.warning("Anthropic authenticity check failed, falling back to rule-based: %s", exc)
        return None


def _gemini_authenticity_check(
    message: str,
    issue_type: str,
    image_bytes: bytes | None = None,
    image_media_type: str | None = None,
) -> AuthenticityResult | None:
    """
    Real vision-capable AI call via Google Gemini. Requires
    AI_ENABLED=true, AI_PROVIDER="gemini", and a valid AI_API_KEY
    from https://aistudio.google.com/app/apikey -- Gemini's free
    tier (Flash models) requires no credit card and no billing setup,
    which makes it a good default while learning/prototyping.

    Uses a plain REST call via httpx (already a base dependency) --
    no extra package install needed for this provider. Calls the
    "gemini-flash-latest" alias (not a pinned version like
    "gemini-2.5-flash") because Google periodically retires pinned
    model IDs -- the alias is maintained by Google to always point
    at their current recommended Flash model, so this stays working
    without needing a code change every time a model is deprecated.

    Returns None on ANY failure so the caller always falls back
    gracefully to the rule-based path.
    """
    if not settings.AI_ENABLED or not settings.AI_API_KEY:
        return None

    try:
        import base64
        import time
        import httpx

        prompt = _authenticity_prompt(message, issue_type)

        parts: list[dict] = [{"text": prompt}]
        if image_bytes and image_media_type:
            parts.append({
                "inline_data": {
                    "mime_type": image_media_type,
                    "data": base64.b64encode(image_bytes).decode(),
                }
            })

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-flash-latest:generateContent?key={settings.AI_API_KEY}"
        )

        # Gemini's free tier occasionally returns 503 (server briefly
        # overloaded) or 429 (rate limit) -- these are transient, not
        # a real problem with the request, so retry a couple of times
        # with a short backoff before giving up and falling back.
        resp = None
        last_exc = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    url,
                    json={"contents": [{"parts": parts}]},
                    timeout=20.0,
                )
                if resp.status_code in (503, 429) and attempt < 2:
                    logger.warning(
                        "Gemini returned %s (attempt %d/3), retrying shortly...",
                        resp.status_code, attempt + 1,
                    )
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code not in (503, 429) or attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_authenticity_response(raw_text)

    except Exception as exc:
        logger.warning("Gemini authenticity check failed, falling back to rule-based: %s", exc)
        return None


def _authenticity_prompt(message: str, issue_type: str) -> str:
    return (
        "You are reviewing a public vehicle-issue report submitted by an "
        "anonymous passerby who scanned a QR sticker on someone's car.\n\n"
        f"Issue type selected: {issue_type}\n"
        f"Reporter's message: {message}\n\n"
        "Judge whether this looks like a genuine report or a prank/spam "
        "submission. If a photo is attached, judge whether it plausibly "
        "supports the message -- specifically check whether the photo "
        "actually shows a vehicle at all, and whether it shows the kind "
        "of issue described. Respond with ONLY a JSON object, no other "
        "text, no markdown code fences, in this exact shape:\n"
        '{"label": "likely_genuine" | "needs_review" | "likely_prank", '
        '"reason": "one short sentence explaining why"}'
    )


def _parse_authenticity_response(raw_text: str) -> AuthenticityResult | None:
    import json as _json

    cleaned = raw_text.strip()
    # Some providers wrap JSON in ```json ... ``` even when told not to.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    parsed = _json.loads(cleaned)
    label = parsed.get("label")
    if label not in ("likely_genuine", "needs_review", "likely_prank"):
        logger.warning("AI returned an unexpected label %r, falling back to rule-based", label)
        return None  # malformed response -- fall back rather than trust a bad label

    return AuthenticityResult(label=label, reason=parsed.get("reason", ""), source="ai")


def assess_authenticity(
    message: str,
    issue_type: str,
    image_bytes: bytes | None = None,
    image_media_type: str | None = None,
) -> AuthenticityResult:
    """
    Public entrypoint: tries the real AI vision call first (Anthropic
    or Gemini, based on AI_PROVIDER), falls back to the rule-based
    heuristic. `has_image` for the rule-based path is just derived
    from whether image bytes were provided.
    """
    provider = (settings.AI_PROVIDER or "anthropic").lower()
    if provider == "gemini":
        ai_result = _gemini_authenticity_check(message, issue_type, image_bytes, image_media_type)
    else:
        ai_result = _anthropic_authenticity_check(message, issue_type, image_bytes, image_media_type)

    if ai_result is not None:
        return ai_result
    return _rule_based_authenticity(message, issue_type, has_image=image_bytes is not None)


# ----------------------------------------------------------------
# Evidence fusion (combined risk score)
#
# Plain-language summary:
#
#   Base risk scoring (score_alert) only looks at message text.
#   Real triage should weigh several independent signals together:
#     - how urgent the wording sounds (base risk)
#     - whether the report looks genuine (authenticity check)
#     - whether a photo backs it up
#     - whether OTHER people reported the same incident (corroboration)
#
#   Two signals from common "AI fraud detection" checklists are
#   deliberately NOT included here: reporter history and GPS location.
#   Reporting on this system is anonymous by design (no account, no
#   phone number required, no location capture) -- that's a stated
#   product decision, not an oversight. Faking those signals with
#   placeholder data would be dishonest. If this system later added
#   optional reporter accounts or captured browser geolocation with
#   consent, those would be legitimate additions to this function.
# ----------------------------------------------------------------


@dataclass
class FusedRiskResult:
    score: int              # 0-100, combined confidence-adjusted urgency
    label: str              # low / medium / high / critical
    reasons: list[str]      # human-readable, always shown to the owner


def _label_for_fused_score(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def fuse_evidence(
    base_risk: RiskResult,
    authenticity: AuthenticityResult,
    corroborating_reports: int,
    has_image: bool,
) -> FusedRiskResult:
    score = base_risk.score * 100
    reasons = [f"Message urgency: {base_risk.label} ({round(base_risk.score * 100)}/100, {base_risk.source})"]

    if authenticity.label == "likely_genuine":
        score += 10
        reasons.append("Authenticity check: likely genuine")
    elif authenticity.label == "likely_prank":
        score -= 30
        reasons.append("Authenticity check: flagged as likely prank -- still shown to owner, not suppressed")
    else:
        reasons.append("Authenticity check: needs manual review")

    if has_image:
        score += 5
        reasons.append("Photo evidence attached")

    if corroborating_reports > 1:
        bonus = min((corroborating_reports - 1) * 15, 30)
        score += bonus
        reasons.append(f"{corroborating_reports} independent reports for this incident")

    score = max(0, min(100, round(score)))
    return FusedRiskResult(score=score, label=_label_for_fused_score(score), reasons=reasons)
