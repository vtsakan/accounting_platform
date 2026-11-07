# core/urls.py

from django.contrib import admin
from django.urls import path, include  # Make sure to import 'include'

urlpatterns = [
    path('admin/', admin.site.urls),
    # This line tells Django that any URL should be handled by the 'accounting' app's urls.
    path('', include('accounting.urls')),
    
]