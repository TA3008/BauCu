"""
WSGI config for baucu project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'baucu.settings')
application = get_wsgi_application()
