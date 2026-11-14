from django.urls import path
from core.urls import urlpatterns as application_urls


def failure(request):
    raise ValueError("Internal S04 fixture failure")


urlpatterns = [path("s04-failure/", failure), *application_urls]
