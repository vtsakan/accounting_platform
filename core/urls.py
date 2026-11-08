# core/urls.py

from django.contrib import admin
from django.urls import path, include  # Make sure to import 'include'
from core import health

urlpatterns = [
    path('health/live/', health.live, name='health-live'),
    path('health/ready/', health.ready, name='health-ready'),
    path('admin/', admin.site.urls),
    # This line tells Django that any URL should be handled by the 'accounting' app's urls.
    path('', include('accounting.urls')),
    
]
