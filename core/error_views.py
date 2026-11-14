from django.shortcuts import render


def csrf_failure(request, reason=""):
    # Never include submitted tokens, cookies or the internal failure reason.
    return render(request, "403.html", status=403)
