"""
The PostHog tracking snippet we give to clients' websites (onboarding helper).

LOADER is copied VERBATIM from PostHog's own documentation (posthog.com/docs/libraries/js, "Option 1:
Add the JavaScript snippet to your HTML") as of 2026-10. It defines a tiny stub, then loads PostHog's
real script asynchronously. If PostHog publishes a new loader, replace LOADER with it.
DEFAULTS is the "config defaults" date PostHog's docs recommend in posthog.init().
"""

LOADER = r"""!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],Object.defineProperty(u,"toString",{configurable:!0,enumerable:!0,writable:!0,value:function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e}}),Object.defineProperty(u.people,"toString",{configurable:!0,enumerable:!0,writable:!0,value:function(){return u.toString(1)+".people (stub)"}}),o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagResult isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);"""

DEFAULTS = "2026-05-30"


def ingestion_host(app_host: str) -> str:
    """The address the browser SENDS events to. For PostHog cloud it differs from the app address:
    https://us.posthog.com -> https://us.i.posthog.com (same for eu). Anything else (self-hosted) is used as is."""
    host = app_host.rstrip("/")
    for region in ("us", "eu"):
        if host == f"https://{region}.posthog.com":
            return f"https://{region}.i.posthog.com"
    return host


def build_snippet(project_token: str, app_host: str) -> str:
    """The complete <script> block to paste before </head>."""
    # The token is a public key (starts with "phc_"), but still make sure it can't break out of the string.
    safe_token = "".join(ch for ch in project_token if ch.isalnum() or ch in "_-")
    return (
        "<script>\n"
        f"    {LOADER}\n"
        f"    posthog.init('{safe_token}', {{\n"
        f"        api_host: '{ingestion_host(app_host)}',\n"
        f"        defaults: '{DEFAULTS}',\n"
        "    })\n"
        "</script>"
    )
