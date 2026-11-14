"""Keep form Origin headers intact without leaking bearer URLs as referrers."""


def referrer_policy(request):
    parts = request.path_info.strip("/").split("/")
    # These routes only exchange bearer URLs for token-free forms. Keep the
    # stricter policy even on an invalid link, a CSRF denial or an error response.
    invitation = len(parts) == 3 and parts[0] == "join"
    reset = (len(parts) == 5 and parts[:3] == ["auth", "password", "reset"]
             and parts[4] != "set-password")
    return "no-referrer" if invitation or reset else "same-origin"
